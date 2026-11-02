"""Stage 2 examples and saved explanations, using synthetic owned programs."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.db import Base
from app.main import (change_sets_count, complete_session, manual_deload, override_target,
                      reschedule, save_set, session_detail, update_exercise,
                      update_muscle_target, update_recovery)
from app.models import Exercise, SessionExercise, User
from app.planning import get_or_create_session, movement_for, prescription
from app.schemas import (ExerciseIn, MuscleTargetIn, OverrideIn, RecoveryIn,
                         RescheduleIn, ResultIn, SetsCountIn)
from app.serializers import exercise_dict
from test_history import START, program
from test_replacement_http import api_program, client, signed_header


def on_day(clock, day):
    clock.set(datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc))


def setup_program(db, sets=3):
    user, template, source_id = program(db)
    exercise = db.get(Exercise, source_id)
    exercise.sets_count, exercise.medium_weight = sets, 60
    db.commit()
    return user, template, exercise


def record(db, user, session, weights, reps=8, rir=2):
    item_id = session.exercises[0].id
    repetitions = [reps] * len(weights) if isinstance(reps, int) else reps
    for index, (weight, repetitions) in enumerate(zip(weights, repetitions), 1):
        save_set(item_id, index, ResultIn(weight=weight, reps=repetitions,
                                        rir_reported=2 if rir is None else rir), user, db)
        db.expire_all()
    complete_session(session.id, user, db)
    db.expire_all()
    if rir is None:
        # Current API requires a real RIR; NULL here represents retained old
        # records, not a new successful API write without the mandatory fact.
        for result in db.get(SessionExercise, item_id).results:
            result.rir_reported = None
        db.commit()
        db.expire_all()
    return item_id


def saved_plan(db, user, session):
    return session_detail(session.id, user, db)["exercises"][0]


@pytest.mark.parametrize("history,expected", [
    ([], (60, 6)),
    ([([50, 47.5, 45], 8, 2)], (50, 9)),
    ([([60, 60, 60], 12, 2)], (62.5, 6)),
    ([([10, 10, 10], 8, 2), ([60, 60, 60], 8, 2),
      ([60, 60, 60], 8, 2), ([62.5, 62.5, 62.5], 8, 2)], (60, 9)),
    ([([60, 60, 60], 4, 2)], (60, 6)),
    ([([60, 60, 60], 8, None)], (60, 6)),
    ([([60, 55, 50], 12, 2)], (62.5, 6)),
    ([([60, 60, 60], 8, 2), ([62.5, 62.5, 62.5], 8, 2)], (62.5, 9)),
])
def test_approved_examples_and_saved_evidence(database, clock, history, expected):
    with database() as db:
        user, template, exercise = setup_program(db)
        old_ids = []
        for offset, (weights, reps, rir) in enumerate(history):
            day = START + timedelta(days=offset)
            on_day(clock, day)
            session = get_or_create_session(db, template, day)
            old_ids.append(record(db, user, session, weights, reps, rir))
        day = START + timedelta(days=len(history))
        on_day(clock, day)
        session = get_or_create_session(db, template, day)
        response = saved_plan(db, user, session)
        assert (response["target_weight"], response["target_reps"]) == expected
        trace = response["recommendation"]
        assert trace["version"] == 1
        assert trace["rules_version"] == "2"
        assert trace["calculated"] == {
            "weight": expected[0], "reps": expected[1],
            "sets_count": response["sets_count"], "rir": 2,
        }
        assert trace["manual_override"] == {}
        assert trace["inputs"] == {"start_weight": 60, "weight_step": 2.5,
                                   "rep_min": 6, "rep_max": 12, "base_sets": 3}
        assert [row["session_exercise_id"] for row in trace["history"]] == list(reversed(old_ids[-3:]))
        for row, (weights, reps, rir) in zip(trace["history"], reversed(history[-3:])):
            assert row["base_weight"] == weights[0]
            assert row["weight_source"] == "first_working"
            assert [result["weight"] for result in row["working_sets"]] == weights
            assert [result["rir"] for result in row["working_sets"]] == [rir] * len(weights)
        assert all(trace[part]["reason"] for part in ("weight", "reps", "sets", "rir"))
        # The same mathematical inputs yield the same weight/reps, independent
        # of repeatedly opening the saved explanation.
        calculated = prescription(db, exercise, session.week, False)
        assert calculated[:2] == expected
        assert saved_plan(db, user, session)["recommendation"] == trace


@pytest.mark.parametrize("reps,expected", [([8, 9], 9), ([9, 10], 11)])
def test_repeat_median_keeps_existing_half_even_rounding(database, clock, reps, expected):
    with database() as db:
        user, template, _ = setup_program(db, sets=2)
        first = get_or_create_session(db, template, START)
        record(db, user, first, [60, 60], reps)
        on_day(clock, START + timedelta(days=1))
        following = get_or_create_session(db, template, START + timedelta(days=1))
        assert saved_plan(db, user, following)["target_reps"] == expected


def test_warmup_and_unfinished_workout_do_not_become_history(database, clock):
    with database() as db:
        user, template, exercise = setup_program(db)
        first = get_or_create_session(db, template, START)
        item = first.exercises[0]
        save_set(item.id, -1, ResultIn(weight=500, reps=100, is_working=False), user, db)
        save_set(item.id, 1, ResultIn(weight=200, reps=12, rir_reported=2), user, db)
        with pytest.raises(HTTPException) as incomplete:
            complete_session(first.id, user, db)
        assert incomplete.value.status_code == 400
        assert prescription(db, exercise, first.week, False)[:2] == (60, 6)
        record(db, user, first, [60, 55, 50])
        on_day(clock, START + timedelta(days=1))
        following = get_or_create_session(db, template, START + timedelta(days=1))
        trace = saved_plan(db, user, following)["recommendation"]
        assert trace["calculated"]["weight"] == 60
        assert len(trace["history"][0]["working_sets"]) == 3
        assert all(row["set_index"] > 0 for row in trace["history"][0]["working_sets"])


def test_legacy_completed_without_working_sets_records_planned_weight_fallback(database, clock):
    with database() as db:
        user, template, _ = setup_program(db)
        first = get_or_create_session(db, template, START)
        first.status, first.completed_at, first.actual_date = "completed", clock.moment, START
        first.exercises[0].target_weight = 70
        db.commit()
        on_day(clock, START + timedelta(days=1))
        following = get_or_create_session(db, template, START + timedelta(days=1))
        row = saved_plan(db, user, following)
        assert (row["target_weight"], row["target_reps"]) == (70, 6)
        assert row["recommendation"]["history"][0]["weight_source"] == "planned"
        assert row["recommendation"]["history"][0]["working_sets"] == []


def test_legacy_incomplete_completed_record_cannot_raise_weight_and_caps_rep_target(database, clock):
    with database() as db:
        user, template, _ = setup_program(db)
        first = get_or_create_session(db, template, START)
        save_set(first.exercises[0].id, 1, ResultIn(weight=60, reps=50, rir_reported=2), user, db)
        # Such a partial record cannot pass today's completion API. It can
        # still exist in retained old data and must not satisfy the all-sets
        # condition merely because its sole working set reached the upper end.
        first.status, first.completed_at, first.actual_date = "completed", clock.moment, START
        db.commit()
        on_day(clock, START + timedelta(days=1))
        following = get_or_create_session(db, template, START + timedelta(days=1))
        row = saved_plan(db, user, following)
        assert (row["target_weight"], row["target_reps"]) == (60, 12)
        assert row["recommendation"]["history"][0]["planned_sets"] == 3
        assert len(row["recommendation"]["history"][0]["working_sets"]) == 1


def test_timed_exercise_has_no_strength_recommendation_or_rir(database):
    with database() as db:
        user, template, _ = program(db, kind="cardio")
        session = get_or_create_session(db, template, START)
        row = saved_plan(db, user, session)
        assert row["recommendation"] is None
        assert row["target_rir"] is None
        assert row["next_set"] is None


def test_saved_explanation_is_immutable_after_program_and_source_fact_changes(database, clock):
    with database() as db:
        user, template, exercise = setup_program(db)
        first = get_or_create_session(db, template, START)
        first_item_id = record(db, user, first, [60, 55, 50])
        on_day(clock, START + timedelta(days=1))
        following = get_or_create_session(db, template, START + timedelta(days=1))
        before = deepcopy(saved_plan(db, user, following))
        exercise.medium_weight, exercise.weight_step, exercise.rep_min = 100, 5, 10
        # Model a corrected external/old source record: an existing target's
        # explanation must never be fabricated anew from changed history.
        db.get(SessionExercise, first_item_id).results[0].weight = 200
        db.commit()
        db.expire_all()
        assert saved_plan(db, user, following) == before


def test_manual_goal_is_separate_from_start_and_recorded_facts(database, clock):
    with database() as db:
        user, template, exercise = setup_program(db)
        first = get_or_create_session(db, template, START)
        original = deepcopy(saved_plan(db, user, first)["recommendation"])
        changed = override_target(first.exercises[0].id, OverrideIn(target_weight=90, target_reps=10), user, db)
        trace = changed["exercises"][0]["recommendation"]
        assert trace["calculated"] == original["calculated"]
        assert trace["manual_override"]["weight"] == 90
        assert trace["manual_override"]["reps"] == 10
        assert float(exercise.medium_weight) == 60
        record(db, user, first, [50, 47.5, 45])
        on_day(clock, START + timedelta(days=1))
        following = get_or_create_session(db, template, START + timedelta(days=1))
        assert saved_plan(db, user, following)["target_weight"] == 50


def test_manual_count_is_explicit_and_complete_current_plan_can_progress(database, clock):
    with database() as db:
        user, template, _ = setup_program(db)
        first = get_or_create_session(db, template, START)
        changed = change_sets_count(first.exercises[0].id, SetsCountIn(sets_count=2), user, db)
        trace = changed["exercises"][0]["recommendation"]
        assert trace["calculated"]["sets_count"] == 3
        assert trace["manual_override"]["sets_count"] == 2
        record(db, user, first, [60, 60], reps=12)
        on_day(clock, START + timedelta(days=1))
        following = get_or_create_session(db, template, START + timedelta(days=1))
        assert saved_plan(db, user, following)["target_weight"] == 62.5


def test_known_manual_goal_survives_explicit_reschedule(database, clock):
    with database() as db:
        user, template, _ = setup_program(db)
        first = get_or_create_session(db, template, START)
        item_id = first.exercises[0].id
        override_target(item_id, OverrideIn(target_weight=77.5, target_reps=9), user, db)
        change_sets_count(item_id, SetsCountIn(sets_count=2), user, db)
        moved = reschedule(first.id, RescheduleIn(scheduled_date=(START + timedelta(days=1)).isoformat()), user, db)
        row = moved["exercises"][0]
        assert (row["target_weight"], row["target_reps"], row["sets_count"]) == (77.5, 9, 2)
        assert row["recommendation"]["manual_override"] == {"weight": 77.5, "reps": 9, "sets_count": 2}


@pytest.mark.parametrize("factory_fixture", ["database", "postgres_database"])
def test_manual_fractional_weight_explanation_matches_stored_precision_after_fresh_get_and_move(request, factory_fixture):
    database = request.getfixturevalue(factory_fixture)
    with database() as db:
        user, template, _ = setup_program(db)
        first = get_or_create_session(db, template, START)
        session_id, item_id, user_id = first.id, first.exercises[0].id, user.telegram_id
        response = override_target(item_id, OverrideIn(target_weight=65.005, target_reps=9), user, db)
        row = response["exercises"][0]
        assert row["recommendation"]["manual_override"]["weight"] == row["target_weight"]

    # SQLite and PostgreSQL can round an input float differently. The contract
    # is that the explanation records each engine's actual stored Numeric,
    # rather than claiming an unrounded request value remains the target.
    with database() as db:
        user = db.get(User, user_id)
        fresh = session_detail(session_id, user, db)["exercises"][0]
        stored_weight = fresh["target_weight"]
        assert stored_weight != 65.005
        assert fresh["recommendation"]["manual_override"]["weight"] == stored_weight
        assert fresh["recommendation"]["calculated"]["weight"] == 60
        moved = reschedule(session_id, RescheduleIn(
            scheduled_date=(START + timedelta(days=1)).isoformat(),
        ), user, db)["exercises"][0]
        assert moved["target_weight"] == stored_weight
        assert moved["recommendation"]["manual_override"]["weight"] == stored_weight
        assert moved["target_reps"] == 9
    with database() as db:
        fresh = session_detail(session_id, db.get(User, user_id), db)["exercises"][0]
        assert fresh["target_weight"] == stored_weight
        assert fresh["recommendation"]["manual_override"]["weight"] == stored_weight


def test_old_unknown_explanation_stays_unknown_when_a_manual_goal_is_recorded(database):
    with database() as db:
        user, template, _ = setup_program(db)
        first = get_or_create_session(db, template, START)
        item = first.exercises[0]
        item.recommendation_context_json = None
        db.commit()
        assert saved_plan(db, user, first)["recommendation"] is None
        changed = override_target(item.id, OverrideIn(target_weight=70, target_reps=8), user, db)
        trace = changed["exercises"][0]["recommendation"]
        assert trace["calculated"] is None
        assert trace["manual_override"] == {"weight": 70, "reps": 8}
        assert not trace.get("history")


@pytest.mark.parametrize("phase,expected,source", [
    ("normal", 2, "accumulation"), ("deload", 4, "deload"),
    ("reentry", 2.5, "reentry"), ("consecutive_deload", 4, "deload"),
])
def test_phase_and_return_rir_priority_is_explained(database, clock, phase, expected, source):
    with database() as db:
        user, template, exercise = setup_program(db)
        exercise.rir_target = 5
        db.commit()
        if phase in ("deload", "reentry", "consecutive_deload"):
            manual_deload(START, user, db)
        first = get_or_create_session(db, template, START)
        session = first
        if phase in ("reentry", "consecutive_deload"):
            record(db, user, first, [60] * first.exercises[0].sets_count, rir=4)
            day = START + timedelta(weeks=1)
            on_day(clock, day)
            if phase == "consecutive_deload":
                manual_deload(day, user, db)
            session = get_or_create_session(db, template, day)
        row = saved_plan(db, user, session)
        assert row["target_rir"] == expected
        assert row["recommendation"]["calculated"]["rir"] == expected
        assert row["recommendation"]["rir"]["source"] == source
        assert float(exercise.rir_target) == 5


@pytest.mark.parametrize("kind", ["growth", "cap", "recovery"])
def test_count_explanation_matches_weekly_growth_limits_and_recovery(database, clock, kind):
    with database() as db:
        user, template, _ = setup_program(db, sets=4 if kind == "cap" else 3)
        if kind == "cap":
            update_muscle_target("Грудь", MuscleTargetIn(min_sets=1, max_sets=2, cap_sets=2), user, db)
        first = get_or_create_session(db, template, START)
        if kind == "cap":
            row = saved_plan(db, user, first)
            assert row["sets_count"] == 2
        else:
            record(db, user, first, [60] * first.exercises[0].sets_count)
            if kind == "recovery":
                update_recovery(START, RecoveryIn(feeling_beat_up=True), user, db)
            on_day(clock, START + timedelta(weeks=1))
            following = get_or_create_session(db, template, START + timedelta(weeks=1))
            row = saved_plan(db, user, following)
            assert row["sets_count"] == (4 if kind == "growth" else 3)
        counts = row["recommendation"]["sets"]
        assert counts["reason"] and counts["reason_code"]
        assert counts["base"] == (4 if kind == "cap" else 3)
        assert row["recommendation"]["calculated"]["sets_count"] == row["sets_count"]
        if kind == "cap":
            assert counts["limited"] is True
            assert counts["before_limits"] == 4
            assert any(limit["group"] == "Грудь" and limit["cap"] == 2 for limit in counts["limits"])


def test_healthy_week_at_twelve_sets_explains_no_addition_despite_available_muscle_capacity(database, clock):
    with database() as db:
        user, template, _ = setup_program(db, sets=12)
        update_muscle_target("Грудь", MuscleTargetIn(min_sets=1, max_sets=20, cap_sets=20), user, db)
        first = get_or_create_session(db, template, START)
        assert first.exercises[0].sets_count == 12
        record(db, user, first, [60] * 12, reps=8, rir=2)
        on_day(clock, START + timedelta(weeks=1))
        following = get_or_create_session(db, template, START + timedelta(weeks=1))
        row = saved_plan(db, user, following)
        counts = row["recommendation"]["sets"]
        assert row["sets_count"] == row["recommendation"]["calculated"]["sets_count"] == 12
        assert counts["reason_code"] == "max_sets"
        assert "12" in counts["reason"]
        assert "прибавки нет" in counts["reason"].lower()
        assert counts["before_limits"] == 12
        assert counts["limited"] is False
        assert any(limit["cap"] >= 13 and limit["before"] == 12 for limit in counts["limits"])


@pytest.mark.parametrize("legacy_rir", [None, 0, 5])
def test_omitted_deprecated_rir_preserves_unknown_zero_or_existing_value(database, legacy_rir):
    with database() as db:
        user, _, exercise = setup_program(db)
        exercise.rir_target = legacy_rir
        db.commit()
        values = exercise_dict(exercise)
        assert values["rir_target"] == legacy_rir
        for field in ("id", "slot_id", "history_id", "rir_target"):
            values.pop(field)
        values["medium_weight"] = 65
        update_exercise(exercise.id, ExerciseIn(**values), user, db)
        db.expire_all()
        assert db.get(Exercise, exercise.id).rir_target == legacy_rir


@pytest.mark.parametrize("legacy_rir", [None, 0])
def test_legacy_movement_link_does_not_replace_real_zero_or_unknown_rir(database, legacy_rir):
    with database() as db:
        user, _, exercise = setup_program(db)
        exercise.movement_id, exercise.rir_target = None, legacy_rir
        db.commit()
        movement_for(db, exercise, user.telegram_id)
        assert exercise.rir_target == legacy_rir


@pytest.mark.parametrize("rir,expected_weight,expected_reps", [(4, 65, 6), (0, 55, 7)])
def test_next_set_has_separate_factual_basis_without_rewriting_plan(database, rir, expected_weight, expected_reps):
    with database() as db:
        user, template, _ = setup_program(db)
        first = get_or_create_session(db, template, START)
        original = deepcopy(saved_plan(db, user, first)["recommendation"])
        item_id = first.exercises[0].id
        # Opening and saving are separate HTTP requests in the app. Expire the
        # empty results relationship loaded above to model the next request.
        db.expire_all()
        result = save_set(item_id, 1, ResultIn(weight=60, reps=8, rir_reported=rir), user, db)
        row = result["exercises"][0]
        suggestion = row["next_set"]
        assert (suggestion["weight"], suggestion["reps"]) == (expected_weight, expected_reps)
        assert suggestion["basis"] == {"set_index": 1, "weight": 60, "reps": 8,
                                        "rir_reported": rir, "target_rir": 2,
                                        "weight_step": 2.5, "rir_difference": rir - 2}
        assert row["recommendation"] == original
        assert (row["target_weight"], row["target_reps"]) == (60, 6)


def test_session_explanation_http_is_read_only_and_owned(client, clock, database):
    one, _, exercise = api_program(client, clock, 1001)
    two = signed_header(2002, clock)
    client.get("/api/me", headers=two).raise_for_status()
    with database() as db:
        template_id = db.get(Exercise, exercise["id"]).template_id
    started = client.post(f"/api/templates/{template_id}/start", headers=one)
    started.raise_for_status()
    path = f'/api/sessions/{started.json()["id"]}'
    with database() as db:
        def all_rows():
            return {table.name: sorted((tuple(row) for row in db.execute(select(table))), key=repr)
                    for table in Base.metadata.sorted_tables}
        before = all_rows()
        first = client.get(path, headers=one)
        assert first.status_code == 200
        assert first.json()["exercises"][0]["recommendation"]["calculated"] is not None
        assert client.get(path, headers=one).json() == first.json()
        assert client.get(path, headers=two).status_code == 404
        assert client.get(path).status_code == 401
        expired = signed_header(1001, clock, auth_date=int(clock.moment.timestamp()) - 86401)
        assert client.get(path, headers=expired).status_code == 401
        db.expire_all()
        assert all_rows() == before
