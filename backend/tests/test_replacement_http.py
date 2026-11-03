"""HTTP contracts with real synthetic Telegram HMAC, without bot startup."""

import hashlib
import hmac
import json
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import auth, main
from app.db import Base, get_db
from app.models import Exercise

TEST_TOKEN = "test-only-key-never-a-real-bot-token"


def signed_header(user_id, clock, auth_date=None):
    fields = {"auth_date": str(int(clock.moment.timestamp()) if auth_date is None else auth_date),
              "user": json.dumps({"id": user_id}, separators=(",", ":")),
              "query_id": "synthetic-query", "signature": "synthetic-Ed25519-signature"}
    check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TEST_TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return {"Authorization": "tma " + urlencode(fields)}


@pytest.fixture
def client(database, clock, monkeypatch):
    def test_db():
        with database() as db:
            yield db

    verify = auth.verify_init_data
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(
        app_env="development", bot_token=TEST_TOKEN, dev_telegram_id=0,
    ))
    monkeypatch.setattr(auth, "verify_init_data", lambda raw, token: verify(
        raw, token, now=int(clock.moment.timestamp()),
    ))
    main.app.dependency_overrides[get_db] = test_db
    # Deliberately not a context manager: TestClient does not run app lifespan,
    # migrations on app.engine, Bot creation, webhook, or reminder task here.
    http = TestClient(main.app)
    try:
        yield http
    finally:
        http.close()
        main.app.dependency_overrides.pop(get_db, None)


def api_program(client, clock, user_id=1001):
    headers = signed_header(user_id, clock)
    movement = client.post("/api/movements", headers=headers, json={
        "name": "Движение A", "kind": "strength", "primary_group": "Грудь",
    })
    movement.raise_for_status()
    template = client.post("/api/templates", headers=headers, json={
        "name": "Синтетический день", "muscle_group": "Грудь", "weekday": 0, "send_time": "09:00",
    })
    template.raise_for_status()
    exercise = client.post(f'/api/templates/{template.json()["id"]}/exercises', headers=headers, json={
        "name": "Движение A", "movement_id": movement.json()["id"], "medium_weight": 80,
        "sets_count": 2, "weight_step": 2.5, "rep_min": 6, "rep_max": 12,
    })
    exercise.raise_for_status()
    return headers, movement.json(), exercise.json()


def replacement_body(movement_id, **changes):
    body = {"movement_id": movement_id, "history_mode": "new", "history_id": None,
            "settings": {"medium_weight": 20, "sets_count": 2, "weight_step": 2.5,
                         "rep_min": 6, "rep_max": 12}}
    body.update(changes)
    return body


def test_replacement_http_rejects_missing_tampered_and_expired_auth(client, clock):
    headers, movement, exercise = api_program(client, clock)
    path = f'/api/exercises/{exercise["id"]}/replace'
    assert client.post(path, json=replacement_body(movement["id"])).status_code == 401
    tampered = {"Authorization": headers["Authorization"].replace("1001", "2002")}
    assert client.post(path, headers=tampered, json=replacement_body(movement["id"])).status_code == 401
    expired = signed_header(1001, clock, auth_date=int(clock.moment.timestamp()) - 86401)
    assert client.post(path, headers=expired, json=replacement_body(movement["id"])).status_code == 401


def test_two_users_cannot_read_or_use_each_others_assignment_movement_or_base(client, clock):
    one, movement_one, exercise_one = api_program(client, clock, 1001)
    two, movement_two, exercise_two = api_program(client, clock, 2002)
    options_path = f'/api/exercises/{exercise_one["id"]}/history-options'
    assert client.get(options_path, headers=two, params={"movement_id": movement_one["id"]}).status_code == 404
    assert client.get(options_path, headers=one, params={"movement_id": movement_two["id"]}).status_code == 404
    assert client.post(f'/api/exercises/{exercise_one["id"]}/replace', headers=two,
                       json=replacement_body(movement_two["id"])).status_code == 404
    assert client.post(f'/api/exercises/{exercise_one["id"]}/replace', headers=one,
                       json=replacement_body(movement_two["id"])).status_code == 404
    assert client.post(f'/api/exercises/{exercise_two["id"]}/replace', headers=two,
                       json=replacement_body(movement_two["id"], history_mode="resume",
                                             history_id=exercise_one["history_id"])).status_code == 404


def test_options_http_does_not_create_weeks_or_workouts(client, clock, database):
    headers, movement, exercise = api_program(client, clock)
    with database() as db:
        before = {table.name: db.scalar(select(func.count()).select_from(table))
                  for table in Base.metadata.sorted_tables}
    for _ in range(2):
        result = client.get(f'/api/exercises/{exercise["id"]}/history-options', headers=headers,
                            params={"movement_id": movement["id"]})
        assert result.status_code == 200
        assert result.json()["options"] == []
    with database() as db:
        assert {table.name: db.scalar(select(func.count()).select_from(table))
                for table in Base.metadata.sorted_tables} == before


@pytest.mark.parametrize("mode", ["new", "resume"])
def test_start_weight_is_required_including_resume_fallback(client, clock, mode):
    headers, movement, exercise = api_program(client, clock)
    settings = {"sets_count": 2, "weight_step": 2.5, "rep_min": 6, "rep_max": 12}
    body = replacement_body(movement["id"], history_mode=mode,
                            history_id=exercise["history_id"] if mode == "resume" else None,
                            settings=settings)
    assert client.post(f'/api/exercises/{exercise["id"]}/replace', headers=headers, json=body).status_code == 422


def test_explicit_zero_is_a_valid_start_and_retry_is_a_conflict(client, clock, database):
    headers, movement, exercise = api_program(client, clock)
    body = replacement_body(movement["id"])
    body["settings"]["medium_weight"] = 0
    path = f'/api/exercises/{exercise["id"]}/replace'
    response = client.post(path, headers=headers, json=body)
    assert response.status_code in (200, 201)
    result = response.json()
    assert result["exercise"]["medium_weight"] == 0
    assert result["exercise"]["id"] != exercise["id"]
    assert result["exercise"]["slot_id"] == exercise["slot_id"]
    assert result["exercise"]["history_id"] != exercise["history_id"]
    assert result["effective_from"] == "next_new_session"
    assert result["preserved_sessions_count"] == 0
    assert client.post(path, headers=headers, json=body).status_code == 409
    with database() as db:
        template_id = db.get(Exercise, result["exercise"]["id"]).template_id
    session = client.post(f"/api/templates/{template_id}/start", headers=headers)
    assert session.status_code == 200
    assert session.json()["exercises"][0]["target_weight"] == 0
    assert session.json()["exercises"][0]["results"] == []
    with database() as db:
        assignments = list(db.scalars(select(Exercise).where(Exercise.slot_id == exercise["slot_id"])))
        assert len(assignments) == 2
        assert sum(item.active for item in assignments) == 1


@pytest.mark.parametrize("kind", ["cardio", "stretch", "other_timed"])
@pytest.mark.parametrize("duration", [None, 0])
def test_timed_replacement_requires_positive_minutes(client, clock, kind, duration):
    headers, _, exercise = api_program(client, clock)
    movement = client.post("/api/movements", headers=headers, json={"name": "Время", "kind": kind}).json()
    body = replacement_body(movement["id"], settings={} if duration is None else {"duration_minutes": duration})
    assert client.post(f'/api/exercises/{exercise["id"]}/replace', headers=headers, json=body).status_code == 422


def test_caller_cannot_supply_slot_or_history_identity_through_settings(client, clock, database):
    headers, movement, exercise = api_program(client, clock, 1001)
    _, _, other = api_program(client, clock, 2002)
    body = replacement_body(movement["id"])
    body["settings"].update(slot_id=other["slot_id"], history_id=other["history_id"])
    response = client.post(f'/api/exercises/{exercise["id"]}/replace', headers=headers, json=body)
    if response.status_code == 422:
        with database() as db:
            assert db.get(Exercise, exercise["id"]).active
    else:
        assert response.status_code in (200, 201)
        assert response.json()["exercise"]["slot_id"] == exercise["slot_id"]
        assert response.json()["exercise"]["history_id"] != other["history_id"]


@pytest.mark.parametrize("route", ["settings", "replace"])
@pytest.mark.parametrize("step,valid", [(0.001, False), (0.015, False), (0.01, True)])
def test_weight_step_matches_two_decimal_storage_without_rounding_to_zero(client, clock, database, route, step, valid):
    headers, movement, exercise = api_program(client, clock)
    if route == "settings":
        body = {key: value for key, value in exercise.items() if key not in ("id", "slot_id", "history_id")}
        body["weight_step"] = step
        response = client.put(f'/api/exercises/{exercise["id"]}', headers=headers, json=body)
    else:
        body = replacement_body(movement["id"])
        body["settings"]["weight_step"] = step
        response = client.post(f'/api/exercises/{exercise["id"]}/replace', headers=headers, json=body)
    if valid:
        assert response.status_code in (200, 201)
        recorded = response.json() if route == "settings" else response.json()["exercise"]
        assert recorded["weight_step"] == 0.01
        with database() as db:
            assert float(db.get(Exercise, recorded["id"]).weight_step) == 0.01
    else:
        assert response.status_code == 422
        with database() as db:
            original = db.get(Exercise, exercise["id"])
            assert original.active
            assert float(original.weight_step) == 2.5
