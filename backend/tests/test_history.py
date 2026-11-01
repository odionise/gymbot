"""Synthetic comparison scenarios shared by the independent implementations."""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.analytics import progress_for_user
from app.main import (
    complete_session, create_exercise, create_movement, create_template,
    delete_exercise, history, manual_deload, next_week_start, save_duration,
    save_set, session_detail, replace_exercise, update_movement,
)
from app.models import Exercise, User, WorkoutTemplate
from app.planning import get_or_create_session
from app.schemas import DurationIn, ExerciseIn, MovementIn, ReplacementIn, ResultIn, TemplateIn

START = date(2026, 10, 26)


def program(db, kind="strength"):
    user = User(telegram_id=1001)
    db.add(user)
    db.commit()
    movement = create_movement(MovementIn(
        name="Движение A", kind=kind,
        primary_group="Грудь" if kind == "strength" else "Не применяется",
    ), user, db)
    template = create_template(TemplateIn(
        name="Синтетический день", muscle_group="Грудь", weekday=0, send_time="09:00",
    ), user, db)
    exercise = create_exercise(template["id"], ExerciseIn(
        name=movement["name"], movement_id=movement["id"], sets_count=2,
        medium_weight=80, weight_step=2.5, rep_min=6, rep_max=12,
        duration_minutes=20 if kind != "strength" else None,
    ), user, db)
    return user, db.get(WorkoutTemplate, template["id"]), exercise["id"]


def replace(db, user, exercise_id, name, kind="strength", weight=20,
            movement_id=None, history_mode="new", history_id=None):
    if movement_id is None:
        movement_id = create_movement(MovementIn(
            name=name, kind=kind,
            primary_group="Грудь" if kind == "strength" else "Не применяется",
        ), user, db)["id"]
    settings = ({"sets_count": 2, "medium_weight": weight, "weight_step": 2.5,
                 "rep_min": 6, "rep_max": 12} if kind == "strength"
                else {"duration_minutes": 30})
    response = replace_exercise(exercise_id, ReplacementIn(
        movement_id=movement_id, history_mode=history_mode,
        history_id=history_id, settings=settings,
    ), user, db)
    db.expire_all()
    return response["exercise"]["id"]


def finish(db, user, session, weight=None):
    # Expire between calls to model separate API requests / DB sessions.
    for item in list(session.exercises):
        if item.skipped:
            continue
        if item.kind == "strength":
            for index in range(1, item.sets_count + 1):
                save_set(item.id, index, ResultIn(
                    weight=float(item.target_weight) if weight is None else weight,
                    reps=8, rir_reported=2,
                ), user, db)
                db.expire_all()
        else:
            save_duration(item.id, DurationIn(minutes=25), user, db)
            db.expire_all()
    completed = complete_session(session.id, user, db)
    db.expire_all()
    return completed


@pytest.mark.history_regression
@pytest.mark.parametrize("previous_kind", ["strength", "cardio", "stretch", "other_timed"])
def test_new_movement_uses_explicit_start_without_other_movement_history(database, clock, previous_kind):
    with database() as db:
        user, template, exercise_id = program(db, previous_kind)
        finish(db, user, get_or_create_session(db, template, START))
        replace(db, user, exercise_id, "Движение B", weight=20)
        clock.set(datetime(2026, 11, 2, 12, tzinfo=timezone.utc))
        following = get_or_create_session(db, template, START + timedelta(weeks=1))
        assert float(following.exercises[0].target_weight) == 20, (
            "B has no own completed workouts: use its explicit 20 kg start, not A's history"
        )


@pytest.mark.history_regression
def test_analytics_keeps_different_movements_in_separate_series(database, clock):
    with database() as db:
        user, template, exercise_id = program(db)
        first = get_or_create_session(db, template, START)
        movement_a = first.exercises[0].movement_id
        finish(db, user, first)
        replace(db, user, exercise_id, "Движение B")
        clock.set(datetime(2026, 11, 2, 12, tzinfo=timezone.utc))
        finish(db, user, get_or_create_session(db, template, START + timedelta(weeks=1)), weight=20)
        series = progress_for_user(db, user.telegram_id)["exercises"]
        assert len(series) == 2, "Two different movements must not share one progress line"
        assert {item["name"] for item in series} == {"Движение A", "Движение B"}
        assert session_detail(first.id, user, db)["exercises"][0]["movement_id"] == movement_a


@pytest.mark.history_regression
def test_strength_timed_strength_roundtrip_does_not_insert_zero_into_weight_base(database, clock):
    with database() as db:
        user, template, exercise_id = program(db)
        finish(db, user, get_or_create_session(db, template, START))
        exercise_id = replace(db, user, exercise_id, "Временное B", kind="cardio")
        clock.set(datetime(2026, 11, 2, 12, tzinfo=timezone.utc))
        finish(db, user, get_or_create_session(db, template, START + timedelta(weeks=1)))
        replace(db, user, exercise_id, "Новое силовое C", weight=30)
        clock.set(datetime(2026, 11, 9, 12, tzinfo=timezone.utc))
        following = get_or_create_session(db, template, START + timedelta(weeks=2))
        assert float(following.exercises[0].target_weight) == 30, (
            "C has no history; neither A's 80 kg nor B's technical zero is a weight base"
        )


@pytest.mark.parametrize("status", ["planned", "in_progress", "completed"])
def test_created_workout_keeps_its_snapshot_when_program_and_catalog_change(database, status):
    with database() as db:
        user, template, exercise_id = program(db)
        session = get_or_create_session(db, template, START)
        item = session.exercises[0]
        if status == "in_progress":
            save_set(item.id, 1, ResultIn(weight=77.5, reps=9, rir_reported=2.5), user, db)
            db.expire_all()
        elif status == "completed":
            finish(db, user, session, weight=77.5)
        before = session_detail(session.id, user, db)["exercises"][0]
        replace(db, user, exercise_id, "Движение B", kind="cardio")
        update_movement(before["movement_id"], MovementIn(
            name="Новое имя в справочнике", kind="strength", primary_group="Грудь",
        ), user, db)
        db.expire_all()
        after = session_detail(session.id, user, db)["exercises"][0]
        stored_fields = (
            "name", "movement_id", "kind", "position", "sets_count", "target_weight",
            "target_reps", "min_reps", "max_reps", "target_rir", "target_duration_minutes",
            "actual_duration_minutes", "primary_group", "secondary_groups", "weight_step", "results",
        )
        assert {key: after[key] for key in stored_fields} == {key: before[key] for key in stored_fields}
        assert session_detail(session.id, user, db)["status"] == status


def test_removing_assignment_preserves_completed_history(database):
    with database() as db:
        user, template, exercise_id = program(db)
        session = get_or_create_session(db, template, START)
        finish(db, user, session)
        before = session_detail(session.id, user, db)
        delete_exercise(exercise_id, user, db)
        assert history(user, db) == [before]


@pytest.mark.parametrize("phase,expected", [("accumulation", 2), ("deload", 4), ("reentry", 2.5)])
def test_week_and_reentry_rir_take_priority_over_assignment(database, clock, phase, expected):
    with database() as db:
        user, template, exercise_id = program(db)
        exercise = db.get(Exercise, exercise_id)
        exercise.rir_target = 5
        db.commit()
        if phase in ("deload", "reentry"):
            manual_deload(START, user, db)
        session = get_or_create_session(db, template, START)
        if phase == "reentry":
            finish(db, user, session)
            clock.set(datetime(2026, 11, 2, 12, tzinfo=timezone.utc))
            session = get_or_create_session(db, template, START + timedelta(weeks=1))
        assert float(session.exercises[0].target_rir) == expected
        assert float(db.get(Exercise, exercise_id).rir_target) == 5


@pytest.mark.parametrize("zone,expected", [
    ("Europe/Moscow", date(2026, 11, 9)),
    ("UTC", date(2026, 11, 2)),
    ("America/New_York", date(2026, 11, 2)),
])
def test_next_week_uses_controlled_time_and_user_timezone(clock, zone, expected):
    clock.set(datetime(2026, 11, 1, 22, tzinfo=timezone.utc))
    assert next_week_start(User(telegram_id=1001, timezone=zone)) == expected
