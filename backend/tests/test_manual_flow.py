"""New manually started workouts keep facts without prescribing targets."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.analytics import progress_for_user
from app.main import (complete_session, last_completed_template_session, save_set,
                      session_detail, start_manual_session, delete_template, change_sets_count)
from app.models import User
from app.planning import get_or_create_session
from app.schemas import ResultIn, SetsCountIn
from test_history import program


def manual_roundtrip(db, clock):
    user, template, _ = program(db)
    clock.set(datetime(2026, 11, 16, 12, tzinfo=timezone.utc))
    first = start_manual_session(template.id, user, db)
    assert first["phase"] == "manual"
    assert first["week_id"] is None
    assert first["entry_mode"] == "manual"
    item = first["exercises"][0]
    assert item["target_weight"] == 0
    assert item["target_reps"] == 0
    assert item["target_rir"] is None
    assert item["recommendation"] is None
    assert start_manual_session(template.id, user, db)["id"] == first["id"]

    save_set(item["id"], -1, ResultIn(weight=20, reps=12, rir_reported=None, is_working=False), user, db)
    save_set(item["id"], 1, ResultIn(weight=72.5, reps=9, rir_reported=1.5), user, db)
    save_set(item["id"], 2, ResultIn(weight=70, reps=10, rir_reported=2), user, db)
    done = complete_session(first["id"], user, db)
    assert done["status"] == "completed"
    assert [(set_["weight"], set_["reps"], set_["rir_reported"])
            for set_ in done["exercises"][0]["results"] if set_["is_working"]] == [(72.5, 9, 1.5), (70, 10, 2)]
    assert last_completed_template_session(template.id, user, db)["id"] == first["id"]
    progress = progress_for_user(db, user.telegram_id)
    assert progress["weeks"][0]["phase"] == "manual"
    assert progress["weeks"][0]["target_low"] is None
    assert progress["weekly_summary"][0]["working_sets"] == 2

    clock.set(clock.moment + timedelta(days=1))
    second = start_manual_session(template.id, user, db)
    assert second["id"] != first["id"]
    assert second["exercises"][0]["target_weight"] == 0
    assert second["exercises"][0]["results"] == []
    assert session_detail(first["id"], user, db)["exercises"][0]["results"] == done["exercises"][0]["results"]

    stranger = User(telegram_id=2002)
    db.add(stranger)
    db.commit()
    with pytest.raises(HTTPException) as exc:
        start_manual_session(template.id, stranger, db)
    assert exc.value.status_code == 404


def test_manual_workout_sqlite(database, clock):
    with database() as db:
        manual_roundtrip(db, clock)


def test_manual_workout_postgresql(postgres_database, clock):
    with postgres_database() as db:
        manual_roundtrip(db, clock)


def test_migration_adds_manual_identity_to_old_rows(database):
    with database() as db:
        assert db.execute(text("SELECT MAX(version) FROM schema_versions")).scalar() == 10
        assert db.execute(text("SELECT COUNT(*) FROM workout_sessions WHERE entry_mode != 'scheduled'")).scalar() == 0


def test_untouched_old_plan_can_be_started_manually(database, clock):
    with database() as db:
        user, template, _ = program(db)
        clock.set(datetime(2026, 11, 16, 12, tzinfo=timezone.utc))
        old = get_or_create_session(db, template, clock.moment.date())
        assert old is not None
        assert old.week_id is not None
        new = start_manual_session(template.id, user, db)
        assert new["id"] == old.id
        assert new["entry_mode"] == "manual"
        assert new["week_id"] is None
        assert new["exercises"][0]["target_weight"] == 0


def test_deleting_template_keeps_recorded_workout(database, clock):
    with database() as db:
        user, template, _ = program(db)
        clock.set(datetime(2026, 11, 16, 12, tzinfo=timezone.utc))
        started = start_manual_session(template.id, user, db)
        item = started["exercises"][0]
        change_sets_count(item["id"], SetsCountIn(sets_count=1), user, db)
        save_set(item["id"], 1, ResultIn(weight=50, reps=8, rir_reported=2), user, db)
        completed = complete_session(started["id"], user, db)
        assert delete_template(template.id, user, db) == {"ok": True}
        assert session_detail(completed["id"], user, db)["exercises"][0]["results"]
        with pytest.raises(HTTPException) as exc:
            start_manual_session(template.id, user, db)
        assert exc.value.status_code == 404
