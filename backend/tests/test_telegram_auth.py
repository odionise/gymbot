"""Telegram bot-token HMAC includes optional fields, including signature.

Synthetic payloads only. No actual bot token, user initData or bot startup.
See https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

import hashlib
import hmac
import json
from datetime import date
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import auth, main
from app.db import get_db
from app.models import User, WorkoutTemplate, WorkoutSession, Exercise, Movement, SetResult

TOKEN = "synthetic-bot-token-for-hmac-regression"


def fields(clock, user_id=1001):
    return {"auth_date": str(int(clock.moment.timestamp())),
            "query_id": "synthetic-query", "chat_type": "sender",
            "chat_instance": "synthetic-instance",
            "signature": "synthetic-Ed25519_signature+/=",
            "user": json.dumps({"id": user_id, "first_name": "Тест + & =", "language_code": "ru"},
                               ensure_ascii=False, separators=(",", ":"))}


def signed(values, *, token=TOKEN, omit_signature_from_hash=False):
    values = dict(values)
    check = "\n".join(f"{key}={value}" for key, value in sorted(values.items())
                      if key != "hash" and not (omit_signature_from_hash and key == "signature"))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


@pytest.mark.parametrize("include_signature", [False, True])
def test_accepts_signed_optional_fields(clock, include_signature):
    values = fields(clock)
    if not include_signature:
        values.pop("signature")
    assert auth.verify_init_data(signed(values), TOKEN, now=int(clock.moment.timestamp())) == 1001


@pytest.mark.parametrize("key", ["signature", "user", "query_id", "chat_instance"])
def test_rejects_tampering_with_any_signed_field(clock, key):
    from urllib.parse import parse_qsl
    values = dict(parse_qsl(signed(fields(clock))))
    values[key] += "changed"
    with pytest.raises(ValueError, match="Invalid Telegram signature"):
        auth.verify_init_data(urlencode(values), TOKEN, now=int(clock.moment.timestamp()))


def test_rejects_hmac_that_omits_present_signature_field(clock):
    with pytest.raises(ValueError, match="Invalid Telegram signature"):
        auth.verify_init_data(signed(fields(clock), omit_signature_from_hash=True), TOKEN,
                              now=int(clock.moment.timestamp()))


@pytest.mark.parametrize("age", [86401, -61])
def test_full_payload_keeps_expiration_checks(clock, age):
    values = fields(clock)
    values["auth_date"] = str(int(clock.moment.timestamp()) - age)
    with pytest.raises(ValueError, match="Expired Telegram authentication"):
        auth.verify_init_data(signed(values), TOKEN, now=int(clock.moment.timestamp()))


@pytest.fixture(params=["database", "postgres_database"], ids=["sqlite", "postgresql"])
def auth_database(request):
    return request.getfixturevalue(request.param)


def test_mini_app_startup_with_full_init_data_and_owner_isolation(auth_database, clock, monkeypatch):
    with auth_database() as db:
        db.add_all([User(telegram_id=1001), User(telegram_id=2002)])
        db.flush()
        movement = Movement(user_id=1001, name="Синтетическое движение", kind="strength",
                            primary_group="Грудь", secondary_groups="", is_anchor=False)
        db.add(movement)
        db.flush()
        for weekday in (0, 3):
            template = WorkoutTemplate(user_id=1001, name=f"День {weekday}", muscle_group="Грудь", weekday=weekday)
            db.add(template)
            db.flush()
            for position in range(7):
                db.add(Exercise(template_id=template.id, name=movement.name, movement_id=movement.id,
                                position=position, sets_count=2, medium_weight=40, weight_step=2.5,
                                rep_min=8, rep_max=12))
        db.commit()

    def dependency():
        with auth_database() as db:
            yield db

    verify = auth.verify_init_data
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(
        app_env="development", bot_token=TOKEN, dev_telegram_id=0))
    monkeypatch.setattr(auth, "verify_init_data", lambda raw, token: verify(
        raw, token, now=int(clock.moment.timestamp())))
    main.app.dependency_overrides[get_db] = dependency
    client = TestClient(main.app)  # No lifespan, real Telegram or reminders.
    try:
        header = {"Authorization": "tma " + signed(fields(clock))}
        for path in ("/api/me", "/api/templates", "/api/sessions/today", "/api/sessions", "/api/sessions/completed-today", "/api/next-week"):
            response = client.get(path, headers=header)
            assert response.status_code == 200, path
            if path == "/api/templates":
                assert len(response.json()) == 2
                assert sum(len(day["exercises"]) for day in response.json()) == 14
        # A gateway can lose the response after a plan was already created.
        # Re-reading today's GET must return that same plan without duplicates.
        today_ids = [item["id"] for item in client.get("/api/sessions/today", headers=header).json()]
        assert len(today_ids) == 1  # Controlled clock is Monday.
        for _ in range(3):
            assert [item["id"] for item in client.get("/api/sessions/today", headers=header).json()] == today_ids
        with auth_database() as db:
            assert db.scalar(select(func.count()).select_from(WorkoutSession)) == 1
            session = db.get(WorkoutSession, today_ids[0])
            session.status = "completed"
            session.actual_date = date(2026, 10, 25)
            session.completed_at = clock.moment
            db.commit()
        assert client.get("/api/sessions/completed-today", headers=header).json() == []
        with auth_database() as db:
            db.get(WorkoutSession, today_ids[0]).actual_date = date(2026, 10, 26)
            db.commit()
        assert [item["id"] for item in client.get("/api/sessions/completed-today", headers=header).json()] == today_ids
        other = {"Authorization": "tma " + signed(fields(clock, 2002))}
        assert client.get("/api/templates", headers=other).json() == []
        assert client.get("/api/sessions/completed-today", headers=other).json() == []
        assert client.get("/api/sessions/completed-today").status_code == 401
        assert client.get("/api/templates").status_code == 401
        bad = {"Authorization": "tma " + signed(fields(clock, 3003), omit_signature_from_hash=True)}
        assert client.get("/api/me", headers=bad).status_code == 401
        with auth_database() as db:
            assert db.get(User, 3003) is None
            assert db.scalar(select(func.count()).select_from(SetResult)) == 0
    finally:
        client.close()
        main.app.dependency_overrides.pop(get_db, None)
