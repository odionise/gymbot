import asyncio
import hashlib
import hmac
import json
from datetime import date, datetime, timezone
from urllib.parse import urlencode

import pytest
from fastapi import Depends, Header
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app import bot as bot_module
from app.analytics import progress_for_user
from app.auth import current_user, verify_init_data
from app.db import Base, get_db, make_engine
from app.main import app
from app.models import Exercise, SetResult, User, WorkoutTemplate, utcnow
from app.planning import get_or_create_session


def signed_init_data(token: str, user_id: int, auth_date: int) -> str:
    fields = {"auth_date": str(auth_date), "user": json.dumps({"id": user_id}, separators=(",", ":"))}
    check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def test_telegram_auth_checks_signature_and_expiry():
    raw = signed_init_data("test-token", 42, 1_800_000_000)
    assert verify_init_data(raw, "test-token", now=1_800_000_005) == 42
    with pytest.raises(ValueError, match="signature"):
        verify_init_data(raw.replace("42", "43"), "test-token", now=1_800_000_005)
    with pytest.raises(ValueError, match="Expired"):
        verify_init_data(raw, "test-token", now=1_800_100_000)


@pytest.fixture
def database(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


def make_program(db: Session, user_id: int = 1, weekday: int = 0):
    user = db.get(User, user_id)
    if not user:
        db.add(User(telegram_id=user_id, chat_id=user_id))
    template = WorkoutTemplate(user_id=user_id, name="Грудь", muscle_group="Грудь", weekday=weekday, send_time="09:00", next_phase=1)
    db.add(template)
    db.flush()
    exercise = Exercise(template_id=template.id, name="Жим лёжа", position=0, sets_count=3, medium_weight=80, weight_step=2.5)
    db.add(exercise)
    db.commit()
    return template, exercise


def record(db: Session, session, reps: int, weight: float | None = None):
    item = session.exercises[0]
    for index in range(1, item.sets_count + 1):
        db.add(SetResult(session_exercise_id=item.id, set_index=index, weight=weight if weight is not None else item.target_weight, reps=reps))
    session.status = "completed"
    session.completed_at = utcnow()
    db.commit()


def test_progression_same_phase_and_two_failures(database):
    with database() as db:
        template, _ = make_program(db)
        first = get_or_create_session(db, template, date(2026, 10, 26))
        assert float(first.exercises[0].target_weight) == 80
        assert first.exercises[0].target_reps == 8
        record(db, first, 8)

        second = get_or_create_session(db, template, date(2026, 11, 2))
        assert second.exercises[0].target_reps == 9
        record(db, second, 12)

        third = get_or_create_session(db, template, date(2026, 11, 9))
        assert float(third.exercises[0].target_weight) == 82.5
        assert third.exercises[0].target_reps == 8
        record(db, third, 7)

        fourth = get_or_create_session(db, template, date(2026, 11, 16))
        assert float(fourth.exercises[0].target_weight) == 82.5
        record(db, fourth, 7)

        fifth = get_or_create_session(db, template, date(2026, 11, 23))
        assert float(fifth.exercises[0].target_weight) == 80


def test_open_session_stays_open_and_phase_isolated(database):
    with database() as db:
        template, _ = make_program(db)
        template.next_phase = 0
        db.commit()
        first = get_or_create_session(db, template, date(2026, 10, 26))
        assert first.phase == 0
        assert float(first.exercises[0].target_weight) == 72.5
        same = get_or_create_session(db, template, date(2026, 11, 2))
        assert same.id == first.id
        record(db, first, 15)
        template.next_phase = 1
        db.commit()
        medium = get_or_create_session(db, template, date(2026, 11, 2))
        assert float(medium.exercises[0].target_weight) == 80
        assert medium.exercises[0].target_reps == 8


def test_group_strength_does_not_compare_medium_with_heavy(database):
    with database() as db:
        template, _ = make_program(db)
        for day in (date(2026, 10, 26), date(2026, 11, 2)):
            medium = get_or_create_session(db, template, day)
            record(db, medium, 8)
        template.next_phase = 2
        db.commit()
        heavy = get_or_create_session(db, template, date(2026, 11, 9))
        record(db, heavy, 6)
        summary = progress_for_user(db, 1)["groups"][0]
        assert summary["strength_change_percent"] == 0


@pytest.fixture
def client(database):
    def db_override():
        with database() as db:
            yield db

    def user_override(x_test_user_id: int = Header(), db: Session = Depends(get_db)):
        user = db.get(User, x_test_user_id)
        if user is None:
            user = User(telegram_id=x_test_user_id)
            db.add(user)
            db.commit()
        return user

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[current_user] = user_override
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_api_draft_completion_and_user_isolation(client):
    user1 = {"X-Test-User-Id": "101"}
    user2 = {"X-Test-User-Id": "202"}
    template = client.post('/api/templates', headers=user1, json={
        "name": "Спина", "muscle_group": "Спина", "weekday": 0, "send_time": "10:00"
    }).json()
    exercise = client.post(f"/api/templates/{template['id']}/exercises", headers=user1, json={
        "name": "Тяга", "sets_count": 2, "medium_weight": 60
    }).json()
    assert exercise["medium_weight"] == 60
    assert client.get(f"/api/templates/{template['id']}/start", headers=user2).status_code == 405
    assert client.post(f"/api/templates/{template['id']}/start", headers=user2).status_code == 404

    session = client.post(f"/api/templates/{template['id']}/start", headers=user1).json()
    item = session["exercises"][0]
    edited = client.patch(f"/api/session-exercises/{item['id']}/target", headers=user1, json={
        "target_weight": 62.5, "target_reps": 13
    }).json()
    assert edited["exercises"][0]["target_weight"] == 62.5
    assert client.patch(f"/api/session-exercises/{item['id']}/target", headers=user2, json={
        "target_weight": 100, "target_reps": 3
    }).status_code == 404
    client.put(f"/api/session-exercises/{item['id']}/sets/1", headers=user1, json={"weight": 62.5, "reps": 13})
    draft = client.get(f"/api/sessions/{session['id']}", headers=user1).json()
    assert draft["status"] == "in_progress"
    assert len(draft["exercises"][0]["results"]) == 1
    assert client.post(f"/api/sessions/{session['id']}/complete", headers=user1).status_code == 400
    client.put(f"/api/session-exercises/{item['id']}/sets/2", headers=user1, json={"weight": 62.5, "reps": 13})
    completed = client.post(f"/api/sessions/{session['id']}/complete", headers=user1).json()
    assert completed["status"] == "completed"
    assert client.get(f"/api/sessions/{session['id']}", headers=user2).status_code == 404
    assert client.get('/api/templates', headers=user2).json() == []


def test_multiple_muscle_groups_are_saved_and_filterable(client):
    headers = {"X-Test-User-Id": "303"}
    template = client.post('/api/templates', headers=headers, json={
        "name": "Грудь и спина", "muscle_group": "Грудь, Спина",
        "weekday": 0, "send_time": "18:30",
    }).json()
    assert template["muscle_group"] == "Грудь, Спина"
    assert client.post('/api/templates', headers=headers, json={
        "name": "Некорректная", "muscle_group": "Грудь, Пресс",
        "weekday": 0, "send_time": "18:30",
    }).status_code == 422
    client.post(f"/api/templates/{template['id']}/exercises", headers=headers, json={
        "name": "Жим лёжа", "sets_count": 1, "medium_weight": 80,
    })
    session = client.post(f"/api/templates/{template['id']}/start", headers=headers).json()
    exercise = session["exercises"][0]
    client.put(f"/api/session-exercises/{exercise['id']}/sets/1", headers=headers, json={
        "weight": 80, "reps": 8,
    })
    assert client.post(f"/api/sessions/{session['id']}/complete", headers=headers).status_code == 200
    progress = client.get('/api/progress', headers=headers).json()
    assert {item["group"] for item in progress["groups"]} == {"Грудь", "Спина"}
    assert progress["exercises"][0]["groups"] == ["Грудь", "Спина"]
    assert progress["exercises"][0]["points"][0]["groups"] == ["Грудь", "Спина"]
    updated = client.put(f"/api/templates/{template['id']}", headers=headers, json={
        "name": "Грудь и спина", "muscle_group": "Спина",
        "weekday": 0, "send_time": "19:15",
    }).json()
    assert updated["muscle_group"] == "Спина"
    assert updated["send_time"] == "19:15"


def test_reminder_only_once_per_day(database, monkeypatch):
    with database() as db:
        make_program(db, user_id=777, weekday=0)
    monkeypatch.setattr(bot_module, "SessionLocal", database)

    class FakeBot:
        def __init__(self):
            self.messages = []

        async def send_message(self, chat_id, text, reply_markup):
            self.messages.append((chat_id, text, reply_markup))
            return type("Sent", (), {"message_id": len(self.messages)})()

    bot = FakeBot()
    moment = datetime(2026, 10, 26, 7, 0, tzinfo=timezone.utc)
    assert asyncio.run(bot_module.send_due_reminders(bot, moment)) == 1
    assert asyncio.run(bot_module.send_due_reminders(bot, moment)) == 0
    assert len(bot.messages) == 1
