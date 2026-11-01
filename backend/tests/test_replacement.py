"""Acceptance scenarios for permanent replacement and explicit history choice."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta, timezone
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.analytics import progress_for_user
from app.db import Base
from app.main import (
    create_exercise, create_movement, create_template, history_options,
    replace_exercise, reschedule, save_set, session_detail,
    update_exercise, update_movement,
)
from app.models import Exercise, User, WorkoutTemplate
from app.planning import get_or_create_session
from app.schemas import ExerciseIn, MovementIn, ReplacementIn, RescheduleIn, ResultIn, TemplateIn
from app.serializers import exercise_dict
from test_history import START, finish, program, replace


def on_day(clock, day):
    clock.set(datetime.combine(day, time(12), timezone.utc))


def settings(exercise, **changes):
    values = exercise_dict(exercise)
    for key in ("id", "slot_id", "history_id"):
        values.pop(key, None)
    values.update(changes)
    return ExerciseIn(**values)


def strength_input(movement_id, **changes):
    values = {"movement_id": movement_id, "history_mode": "new", "history_id": None,
              "settings": {"sets_count": 2, "medium_weight": 20, "weight_step": 2.5,
                           "rep_min": 6, "rep_max": 12}}
    values.update(changes)
    return ReplacementIn(**values)


def row_counts(db):
    return {table.name: db.scalar(select(func.count()).select_from(table))
            for table in Base.metadata.sorted_tables}


@pytest.mark.parametrize("mode,expected_weight", [("resume", 80), ("new", 30)])
def test_return_can_continue_exact_base_or_start_a_separate_one(database, clock, mode, expected_weight):
    with database() as db:
        user, template, source_id = program(db)
        first = get_or_create_session(db, template, START)
        movement_a = first.exercises[0].movement_id
        history_a = db.get(Exercise, source_id).history_id
        slot = db.get(Exercise, source_id).slot_id
        finish(db, user, first)
        second_id = replace(db, user, source_id, "Движение B")
        on_day(clock, START + timedelta(days=1))
        finish(db, user, get_or_create_session(db, template, START + timedelta(days=1)))
        choices = history_options(second_id, movement_a, user, db)["options"]
        assert [choice["history_id"] for choice in choices] == [history_a]
        assert choices[0]["completed_sessions"] == 1
        third_id = replace(db, user, second_id, "Движение A", weight=30,
                           movement_id=movement_a, history_mode=mode,
                           history_id=history_a if mode == "resume" else None)
        third = db.get(Exercise, third_id)
        assert third.id not in {source_id, second_id}
        assert third.slot_id == slot
        assert (third.history_id == history_a) is (mode == "resume")
        assert not db.get(Exercise, source_id).active
        assert not db.get(Exercise, second_id).active
        on_day(clock, START + timedelta(days=2))
        returned = get_or_create_session(db, template, START + timedelta(days=2))
        assert float(returned.exercises[0].target_weight) == expected_weight
        finish(db, user, returned)
        series = progress_for_user(db, user.telegram_id)["exercises"]
        assert len(series) == (2 if mode == "resume" else 3)
        assert len({item["id"] for item in series}) == len(series)
        if mode == "resume":
            continued = next(item for item in series if item["history_id"] == history_a)
            assert len(continued["points"]) == 2


def test_multiple_previous_bases_require_exact_selection(database, clock):
    with database() as db:
        user, template, first_id = program(db)
        movement_a = db.get(Exercise, first_id).movement_id
        history_a = db.get(Exercise, first_id).history_id
        finish(db, user, get_or_create_session(db, template, START))
        second_id = replace(db, user, first_id, "Движение B")
        movement_b = db.get(Exercise, second_id).movement_id
        on_day(clock, START + timedelta(days=1))
        finish(db, user, get_or_create_session(db, template, START + timedelta(days=1)))
        third_id = replace(db, user, second_id, "Движение A", weight=30, movement_id=movement_a)
        second_history_a = db.get(Exercise, third_id).history_id
        on_day(clock, START + timedelta(days=2))
        finish(db, user, get_or_create_session(db, template, START + timedelta(days=2)))
        fourth_id = replace(db, user, third_id, "Движение B", movement_id=movement_b)
        options = history_options(fourth_id, movement_a, user, db)["options"]
        assert {choice["history_id"] for choice in options} == {history_a, second_history_a}
        fifth_id = replace(db, user, fourth_id, "Движение A", weight=35,
                           movement_id=movement_a, history_mode="resume", history_id=history_a)
        on_day(clock, START + timedelta(days=3))
        resumed = get_or_create_session(db, template, START + timedelta(days=3))
        assert resumed.exercises[0].exercise_id == fifth_id
        assert float(resumed.exercises[0].target_weight) == 80


@pytest.mark.parametrize("kind", ["cardio", "stretch", "other_timed"])
def test_strength_timed_strength_roundtrip_records_correct_units(database, clock, kind):
    with database() as db:
        user, template, source_id = program(db)
        finish(db, user, get_or_create_session(db, template, START))
        timed_id = replace(db, user, source_id, "На время", kind=kind)
        on_day(clock, START + timedelta(days=1))
        timed = get_or_create_session(db, template, START + timedelta(days=1))
        item = timed.exercises[0]
        assert item.exercise_id == timed_id
        assert item.kind == kind
        assert item.target_duration_minutes == 30
        assert item.sets_count == 0
        assert item.target_rir is None
        recorded = finish(db, user, timed)
        assert recorded["exercises"][0]["actual_duration_minutes"] == 25
        assert len(progress_for_user(db, user.telegram_id)["exercises"]) == 1
        last_id = replace(db, user, timed_id, "Новое силовое", weight=30)
        on_day(clock, START + timedelta(days=2))
        following = get_or_create_session(db, template, START + timedelta(days=2))
        assert following.exercises[0].exercise_id == last_id
        assert float(following.exercises[0].target_weight) == 30
        assert following.exercises[0].target_duration_minutes is None
        finish(db, user, following)
        assert len(progress_for_user(db, user.telegram_id)["exercises"]) == 2


@pytest.mark.parametrize("other_day", [False, True])
def test_same_movement_in_another_slot_or_day_is_not_a_return_option(database, clock, other_day):
    with database() as db:
        user, template, first_id = program(db)
        movement_a = db.get(Exercise, first_id).movement_id
        history_a = db.get(Exercise, first_id).history_id
        finish(db, user, get_or_create_session(db, template, START))
        second_id = replace(db, user, first_id, "Движение B")
        other_template = template
        if other_day:
            created = create_template(TemplateIn(name="Другой день", muscle_group="Грудь",
                                                weekday=1, send_time="10:00"), user, db)
            other_template = db.get(WorkoutTemplate, created["id"])
        other = create_exercise(other_template.id, ExerciseIn(
            name="Движение A", movement_id=movement_a, position=7, sets_count=2,
            medium_weight=60, weight_step=2.5, rep_min=6, rep_max=12,
        ), user, db)
        db.expire_all()
        on_day(clock, START + timedelta(days=1))
        finish(db, user, get_or_create_session(db, other_template, START + timedelta(days=1)))
        assert [option["history_id"] for option in history_options(second_id, movement_a, user, db)["options"]] == [history_a]
        with pytest.raises(HTTPException) as rejected:
            replace(db, user, second_id, "Движение A", movement_id=movement_a,
                    history_mode="resume", history_id=other["history_id"])
        assert rejected.value.status_code == 409
        assert db.get(Exercise, second_id).active


def test_used_catalog_type_and_settings_endpoint_cannot_bypass_replacement(database):
    with database() as db:
        user, template, exercise_id = program(db)
        exercise = db.get(Exercise, exercise_id)
        movement_a = exercise.movement_id
        different = create_movement(MovementIn(name="Другое движение", primary_group="Грудь"), user, db)
        with pytest.raises(HTTPException) as changed:
            update_exercise(exercise_id, settings(exercise, movement_id=different["id"]), user, db)
        assert changed.value.status_code == 409
        with pytest.raises(HTTPException) as changed_type:
            update_movement(movement_a, MovementIn(name="Движение A", kind="cardio"), user, db)
        assert changed_type.value.status_code == 409
        unused = create_movement(MovementIn(name="Не использовано", primary_group="Грудь"), user, db)
        assert update_movement(unused["id"], MovementIn(name="Теперь кардио", kind="cardio"), user, db)["kind"] == "cardio"
        assert db.get(Exercise, exercise_id).movement_id == movement_a


def test_created_snapshot_uses_its_own_weight_step_after_settings_edit(database):
    with database() as db:
        user, template, exercise_id = program(db)
        session = get_or_create_session(db, template, START)
        item_id = session.exercises[0].id
        before = session_detail(session.id, user, db)
        update_exercise(exercise_id, settings(db.get(Exercise, exercise_id), weight_step=5,
                                             medium_weight=90, sets_count=3), user, db)
        db.expire_all()
        assert session_detail(session.id, user, db) == before
        db.expire_all()
        saved = save_set(item_id, 1, ResultIn(weight=80, reps=8, rir_reported=4), user, db)
        assert saved["exercises"][0]["weight_step"] == 2.5
        assert saved["exercises"][0]["next_set"]["weight"] == 85


def test_old_unknown_weight_step_keeps_manual_recording_without_suggestion(database):
    with database() as db:
        user, template, _ = program(db)
        session = get_or_create_session(db, template, START)
        item = session.exercises[0]
        item.weight_step = None
        db.commit()
        saved = save_set(item.id, 1, ResultIn(weight=77.5, reps=8, rir_reported=4), user, db)
        assert saved["exercises"][0]["weight_step"] is None
        assert saved["exercises"][0]["next_set"] is None
        assert saved["exercises"][0]["results"][0]["weight"] == 77.5


def test_created_workout_is_kept_and_its_reschedule_is_rejected_after_replacement(database):
    with database() as db:
        user, template, source_id = program(db)
        session = get_or_create_session(db, template, START)
        before = session_detail(session.id, user, db)
        replace(db, user, source_id, "Движение B")
        assert get_or_create_session(db, template, START + timedelta(days=1)).id == session.id
        assert reschedule(session.id, RescheduleIn(scheduled_date=START.isoformat()), user, db) == before
        counts = row_counts(db)
        with pytest.raises(HTTPException) as rejected:
            reschedule(session.id, RescheduleIn(scheduled_date=(START + timedelta(days=1)).isoformat()), user, db)
        assert rejected.value.status_code == 409
        assert session_detail(session.id, user, db) == before
        assert row_counts(db) == counts


def test_history_options_are_read_only_and_repeat_does_not_create_a_duplicate(database):
    with database() as db:
        user, template, source_id = program(db)
        first = get_or_create_session(db, template, START)
        movement_a = first.exercises[0].movement_id
        finish(db, user, first)
        second_id = replace(db, user, source_id, "Движение B")
        counts = row_counts(db)
        assert history_options(second_id, movement_a, user, db)["options"]
        assert history_options(second_id, movement_a, user, db)["options"]
        assert row_counts(db) == counts
        movement_b = db.get(Exercise, second_id).movement_id
        with pytest.raises(HTTPException) as repeated:
            replace_exercise(source_id, strength_input(movement_b), user, db)
        assert repeated.value.status_code == 409
        assert row_counts(db) == counts


@pytest.mark.parametrize("legacy_kind", ["mixed", "unknown"])
def test_ambiguous_legacy_base_is_not_resumable_or_combined(database, clock, legacy_kind):
    with database() as db:
        user, template, source_id = program(db)
        movement_a = db.get(Exercise, source_id).movement_id
        first = get_or_create_session(db, template, START)
        finish(db, user, first)
        if legacy_kind == "unknown":
            first.exercises[0].movement_id = None
            for result in first.exercises[0].results:
                result.weight = 200
            db.commit()
        else:
            movement_b = create_movement(MovementIn(name="Старое B", primary_group="Грудь"), user, db)
            # Reproduce old in-place replacement as synthetic pre-migration data.
            exercise = db.get(Exercise, source_id)
            exercise.movement_id, exercise.name, exercise.medium_weight = movement_b["id"], "Старое B", 20
            db.commit()
            db.expire_all()
            on_day(clock, START + timedelta(days=1))
            following = get_or_create_session(db, template, START + timedelta(days=1))
            assert float(following.exercises[0].target_weight) == 20
            finish(db, user, following)
        before = row_counts(db)
        options = history_options(source_id, movement_a, user, db)
        assert options["options"] == []
        assert options["excluded_legacy"] is True
        assert row_counts(db) == before
        if legacy_kind == "mixed":
            series = progress_for_user(db, user.telegram_id)["exercises"]
            assert len(series) == 2
            assert all(len(item["points"]) == 1 for item in series)
        else:
            on_day(clock, START + timedelta(days=1))
            following = get_or_create_session(db, template, START + timedelta(days=1))
            assert float(following.exercises[0].target_weight) == 80
            assert first.exercises[0].movement_id is None


def test_database_rejects_two_active_assignments_in_one_slot(database):
    with database() as db:
        _, _, source_id = program(db)
        source = db.get(Exercise, source_id)
        db.add(Exercise(id=str(uuid4()), template_id=source.template_id, movement_id=source.movement_id,
                        slot_id=source.slot_id, history_id=source.history_id, name="Дубликат",
                        position=0, sets_count=2, medium_weight=20, weight_step=2.5, active=True))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
        assert db.scalar(select(func.count()).select_from(Exercise).where(Exercise.active.is_(True))) == 1


def test_postgresql_concurrent_replacement_has_one_winner(postgres_database):
    with postgres_database() as db:
        user, _, source_id = program(db)
        user_id = user.telegram_id
        slot_id = db.get(Exercise, source_id).slot_id
        movements = [create_movement(MovementIn(name=name, primary_group="Грудь"), user, db)["id"]
                     for name in ("Вариант B", "Вариант C")]
    barrier = Barrier(2)

    def request(movement_id):
        with postgres_database() as db:
            user = db.get(User, user_id)
            barrier.wait(timeout=10)
            try:
                replace_exercise(source_id, strength_input(movement_id), user, db)
                return "replaced"
            except HTTPException as error:
                return error.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(request, movements))
    assert sorted(map(str, results)) == ["409", "replaced"]
    with postgres_database() as db:
        assert db.scalar(select(func.count()).select_from(Exercise).where(Exercise.slot_id == slot_id)) == 2
        assert db.scalar(select(func.count()).select_from(Exercise).where(
            Exercise.slot_id == slot_id, Exercise.active.is_(True))) == 1


def test_postgresql_start_and_replacement_keep_a_coherent_snapshot(postgres_database):
    with postgres_database() as db:
        user, template, source_id = program(db)
        user_id, template_id = user.telegram_id, template.id
        old_movement = db.get(Exercise, source_id).movement_id
        new_movement = create_movement(MovementIn(name="Движение B", primary_group="Грудь"), user, db)["id"]
    barrier = Barrier(2)

    def start_request():
        with postgres_database() as db:
            template = db.get(WorkoutTemplate, template_id)
            list(template.exercises)  # Intentionally preload the pre-replacement relation.
            barrier.wait(timeout=10)
            session = get_or_create_session(db, template, START)
            item = session.exercises[0]
            return session.id, item.exercise_id, item.movement_id, item.name, float(item.target_weight)

    def replacement_request():
        with postgres_database() as db:
            user = db.get(User, user_id)
            barrier.wait(timeout=10)
            return replace_exercise(source_id, strength_input(new_movement), user, db)["exercise"]["id"]

    with ThreadPoolExecutor(max_workers=2) as executor:
        starting = executor.submit(start_request)
        replacing = executor.submit(replacement_request)
        session_id, assignment_id, movement_id, name, weight = starting.result(timeout=20)
        replacement_id = replacing.result(timeout=20)
    assert (assignment_id, movement_id, name, weight) in {
        (source_id, old_movement, "Движение A", 80),
        (replacement_id, new_movement, "Движение B", 20),
    }
    with postgres_database() as db:
        template = db.get(WorkoutTemplate, template_id)
        assert get_or_create_session(db, template, START).id == session_id
        assert db.get(Exercise, replacement_id).active
