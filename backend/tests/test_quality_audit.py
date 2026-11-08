"""Synthetic audit regressions; never start a bot or the application lifespan."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event, Lock
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event, func, select

from app.analytics import progress_for_user
from app.history import completion_timestamp
from app import auth, main
from app.db import get_db
from app.main import complete_session, create_exercise, create_template, manual_deload, movements, save_set, set_next_week, update_movement
from app.models import Exercise, Mesocycle, Movement, SessionExercise, SetResult, TrainingWeek, User, WorkoutSession
from app.planning import get_or_create_session, latest_accumulation, prescription, resolve_week, week_stats
from app.schemas import ExerciseIn, MovementIn, NextWeekIn, ResultIn, TemplateIn
from test_history import START, program
from test_replacement_http import signed_header, TEST_TOKEN


@pytest.fixture(params=["database", "postgres_database"], ids=["sqlite", "postgresql"])
def audit_database(request):
    return request.getfixturevalue(request.param)


@pytest.fixture
def audit_http(audit_database, clock, monkeypatch):
    def dependency():
        with audit_database() as db:
            yield db

    verify = auth.verify_init_data
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(
        app_env="development", bot_token=TEST_TOKEN, dev_telegram_id=0))
    monkeypatch.setattr(auth, "verify_init_data", lambda raw, token: verify(
        raw, token, now=int(clock.moment.timestamp())))
    main.app.dependency_overrides[get_db] = dependency
    client = TestClient(main.app)  # No lifespan, bot, webhook or notifications.
    try:
        yield client
    finally:
        client.close()
        main.app.dependency_overrides.pop(get_db, None)


def test_locked_write_routes_preserve_telegram_auth_and_owner(audit_database, audit_http, clock):
    with audit_database() as db:
        user, template, _ = program(db)
        session = get_or_create_session(db, template, START)
        session_id, item_id = session.id, session.exercises[0].id
        db.add(User(telegram_id=2002))
        db.commit()
    base = f"/api/session-exercises/{item_id}"
    writes = [("PUT", base + "/sets/1", {"weight": 80, "reps": 8, "rir_reported": 2}),
              ("DELETE", base + "/sets/1", None),
              ("PATCH", base + "/target", {"target_weight": 80, "target_reps": 8}),
              ("PATCH", base + "/sets-count", {"sets_count": 1}),
              ("PATCH", base + "/skip", {"skipped": True}),
              ("PUT", base + "/duration", {"minutes": 20}),
              ("DELETE", base + "/duration", None),
              ("POST", f"/api/sessions/{session_id}/complete", None),
              ("PATCH", f"/api/sessions/{session_id}/reschedule", {"scheduled_date": "2026-10-27"})]
    for method, path, body in writes:
        assert audit_http.request(method, path, json=body).status_code == 401
        assert audit_http.request(method, path, json=body,
                                  headers=signed_header(2002, clock)).status_code == 404
    with audit_database() as db:
        assert db.scalar(select(func.count()).select_from(SetResult)) == 0
        assert db.get(WorkoutSession, session_id).status == "planned"
        assert not db.get(SessionExercise, item_id).skipped


@pytest.mark.parametrize("source_phase", ["accumulation", "deload"])
def test_late_completion_preserves_plan_phase_and_counts_actual_week(audit_database, clock, source_phase):
    with audit_database() as db:
        user, template, _ = program(db)
        if source_phase == "deload":
            manual_deload(START, user, db)
        session = get_or_create_session(db, template, START)
        original_week_id = session.week_id
        item = session.exercises[0]
        original_goal = (item.target_weight, item.target_reps, item.target_rir, item.sets_count)
        for index in range(1, item.sets_count + 1):
            save_set(item.id, index, ResultIn(weight=80, reps=8, rir_reported=2), user, db)
            db.expire_all()  # Each real API request has a fresh ORM session.
        later = START + timedelta(days=7)
        if source_phase == "accumulation":
            manual_deload(later, user, db)
        clock.set(datetime.combine(later, datetime.min.time(), timezone.utc) + timedelta(hours=12))
        result = complete_session(session.id, user, db)
        assert result["phase_type"] == source_phase
        assert result["week_id"] == original_week_id
        assert result["actual_date"] == later.isoformat()
        db.expire_all()
        stored = db.get(SessionExercise, item.id)
        assert (stored.target_weight, stored.target_reps, stored.target_rir, stored.sets_count) == original_goal
        assert week_stats(db, user.telegram_id, later)["working"] == {"Грудь": item.sets_count}
        assert week_stats(db, user.telegram_id, START)["working"] == {}


@pytest.mark.parametrize("changes", [{"rep_min": 15}, {"rep_max": 5}])
def test_partial_rep_bounds_cannot_conflict_with_legacy_fallback(changes):
    with pytest.raises(ValidationError):
        ExerciseIn(name="Synthetic", **changes)
    assert ExerciseIn(name="Synthetic", rep_min=6).rep_min == 6


def test_zero_is_not_an_invisible_sixth_warmup(audit_database):
    with audit_database() as db:
        user, template, _ = program(db)
        session = get_or_create_session(db, template, START)
        with pytest.raises(HTTPException) as error:
            save_set(session.exercises[0].id, 0, ResultIn(weight=20, reps=8, is_working=False), user, db)
        assert error.value.status_code == 400
        assert db.scalar(select(func.count()).select_from(SetResult)) == 0


def overlap_reads(engine, fragment):
    """Allow an unsafe read/read/write race; a proper lock may serialize it.

    The first matching SELECT briefly waits for the second. With serialization
    the wait expires normally, so this probe does not require two readers to
    enter a protected region and cannot deadlock the fixed implementation.
    """
    guard, ready = Lock(), Event()
    calls = 0

    def after_select(connection, cursor, statement, parameters, context, executemany):
        nonlocal calls
        if not statement.lstrip().upper().startswith("SELECT") or fragment not in statement.lower():
            return
        with guard:
            calls += 1
            current = calls
            if current == 2:
                ready.set()
        if current == 1:
            ready.wait(0.3)

    event.listen(engine, "after_cursor_execute", after_select)
    return after_select


def test_simultaneous_put_of_same_set_is_idempotent(audit_database):
    with audit_database() as db:
        user, template, _ = program(db)
        session = get_or_create_session(db, template, START)
        item_id = session.exercises[0].id
    engine = audit_database.kw["bind"]
    listener = overlap_reads(engine, "set_results.set_index =")
    start = Barrier(2)

    def write():
        with audit_database() as db:
            user = db.get(User, 1001)
            start.wait(timeout=5)
            try:
                save_set(item_id, 1, ResultIn(weight=80, reps=8, rir_reported=2), user, db)
                return "ok"
            except Exception as exc:
                return type(exc).__name__

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: write(), range(2)))
    finally:
        event.remove(engine, "after_cursor_execute", listener)
    assert outcomes == ["ok", "ok"]
    with audit_database() as db:
        assert db.scalar(select(func.count()).select_from(SetResult)) == 1


def test_two_days_starting_together_share_one_week(audit_database):
    with audit_database() as db:
        user, first, source_id = program(db)
        source = db.get(Exercise, source_id)
        second = create_template(TemplateIn(name="Other day", muscle_group="Грудь", weekday=1,
                                            send_time="09:00"), user, db)
        create_exercise(second["id"], ExerciseIn(name="Synthetic", movement_id=source.movement_id,
                                               sets_count=2), user, db)
        template_ids = [first.id, second["id"]]
    engine = audit_database.kw["bind"]
    listener = overlap_reads(engine, "training_weeks.week_start =")
    start = Barrier(2)

    def create(template_id):
        from app.models import WorkoutTemplate
        with audit_database() as db:
            template = db.get(WorkoutTemplate, template_id)
            start.wait(timeout=5)
            try:
                return get_or_create_session(db, template, START).week_id
            except Exception as exc:
                return type(exc).__name__

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(create, template_ids))
    finally:
        event.remove(engine, "after_cursor_execute", listener)
    with audit_database() as db:
        weeks = list(db.scalars(select(TrainingWeek)))
        assert len(weeks) == 1
        assert outcomes == [weeks[0].id, weeks[0].id]
        assert db.scalar(select(func.count()).select_from(Mesocycle)) == 1
        assert db.scalar(select(func.count()).select_from(WorkoutSession)) == 2


def test_progress_loads_history_in_batches_without_changing_totals(audit_database):
    with audit_database() as db:
        user, template, source_id = program(db)
        movement_id = db.get(Exercise, source_id).movement_id
        for offset in range(12):
            day = START - timedelta(days=7 * offset)
            session = WorkoutSession(user_id=user.telegram_id, template_id=template.id,
                                     template_name=template.name, muscle_group="Грудь", scheduled_date=day,
                                     actual_date=day, status="completed", phase=1, phase_type="accumulation",
                                     completed_at=datetime.combine(day, datetime.min.time(), timezone.utc))
            db.add(session)
            db.flush()
            item = SessionExercise(session_id=session.id, exercise_id=source_id, movement_id=movement_id,
                                   name="Synthetic", kind="strength", position=0, sets_count=1,
                                   target_weight=80, target_reps=8, min_reps=6, max_reps=12,
                                   primary_group="Грудь")
            db.add(item)
            db.flush()
            db.add(SetResult(session_exercise_id=item.id, set_index=1, weight=80, reps=8,
                             rir_reported=2, is_working=True))
        db.commit()
    queries = []
    engine = audit_database.kw["bind"]

    def count_queries(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            queries.append(statement)

    event.listen(engine, "before_cursor_execute", count_queries)
    try:
        with audit_database() as db:
            result = progress_for_user(db, 1001)
    finally:
        event.remove(engine, "before_cursor_execute", count_queries)
    assert len(result["exercises"][0]["points"]) == 12
    assert sum(row["tonnage"] for row in result["weeks"]) == 12 * 80 * 8
    assert sum(row["working_sets"] for row in result["weeks"]) == 12
    assert len(queries) <= 8, f"History used {len(queries)} SELECTs for 12 workouts"
    print(f"Synthetic history: 12 workouts, {len(queries)} SELECTs, tonnage preserved")


@pytest.mark.parametrize("primary", ["Грудь", None])
def test_overall_summary_counts_each_fact_once_and_preserves_unknowns(audit_database, clock, primary):
    with audit_database() as db:
        user, template, _ = program(db)
        session = get_or_create_session(db, template, START)
        item = session.exercises[0]
        item.primary_group, item.secondary_groups = primary, "Трицепс"
        for index, weight, reps, rir, working in [(1, 80, 8, 2, True),
                                                  (2, 70, 10, None, True),
                                                  (-1, 20, 10, None, False)]:
            db.add(SetResult(session_exercise_id=item.id, set_index=index, weight=weight,
                             reps=reps, rir_reported=rir, is_working=working))
        session.status, session.actual_date, session.completed_at = "completed", START, clock.moment
        db.commit()
    with audit_database() as db:
        result = progress_for_user(db, 1001)
        total = result["weekly_summary"][0]
        assert total["working_sets"] == 2
        assert total["hard_sets"] == 1  # Only the result whose RIR is known.
        assert total["tonnage"] == 1340  # 80*8 + 70*10, no muscle duplication/warmup.
        assert total["avg_rir"] == 2
        assert (total["rir_known_sets"], total["rir_unknown_sets"]) == (1, 1)
        assert total["target_low"] is None and total["target_high"] is None
        if primary:
            by_group = {row["group"]: row for row in result["weeks"]}
            assert by_group["Грудь"]["tonnage"] == 1340
            assert by_group["Трицепс"]["tonnage"] == 670
        else:
            assert result["weeks"] == []  # Never invent muscle attribution.
        rows = list(db.scalars(select(SetResult).order_by(SetResult.set_index)))
        assert [(float(r.weight), r.reps, r.rir_reported is None) for r in rows] == [
            (20, 10, True), (80, 8, False), (70, 10, True)]


def test_legacy_facts_remain_in_overall_summary_without_invented_rir_or_phase(audit_database, clock):
    with audit_database() as db:
        user, template, _ = program(db)
        session = get_or_create_session(db, template, START)
        item = session.exercises[0]
        db.add(SetResult(session_exercise_id=item.id, set_index=1, weight=80, reps=8,
                         rir_reported=None, is_working=True))
        session.phase_type, session.week_id = None, None
        session.status, session.actual_date, session.completed_at = "completed", START, clock.moment
        # A historical record may predate the modern training-week model.
        for week in db.scalars(select(TrainingWeek)):
            db.delete(week)
        db.commit()
    with audit_database() as db:
        result = progress_for_user(db, 1001)
        total = result["weekly_summary"][0]
        assert total["tonnage"] == 640 and total["working_sets"] == 1
        assert total["phase"] == "unknown"
        assert total["avg_rir"] is None and total["rir_unknown_sets"] == 1
        assert result["weeks"] == []  # Keep the existing muscle-RIR cohort.


def test_catalog_usage_is_batched_and_owner_filtered(audit_database):
    with audit_database() as db:
        user, _, exercise_id = program(db)
        used = db.get(Exercise, exercise_id).movement_id
        db.get(Exercise, exercise_id).active = False  # Still used in the past.
        db.add(User(telegram_id=2002))
        db.flush()
        for index in range(20):
            db.add(Movement(user_id=1001, name=f"Synthetic {index}", kind="strength", primary_group="Грудь"))
        db.add(Movement(user_id=2002, name="Other user's movement", kind="strength", primary_group="Грудь"))
        db.commit()
    queries = []
    engine = audit_database.kw["bind"]

    def record_query(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            queries.append(statement)

    with audit_database() as db:
        user = db.get(User, 1001)
        event.listen(engine, "before_cursor_execute", record_query)
        try:
            result = movements(user, db)
        finally:
            event.remove(engine, "before_cursor_execute", record_query)
    assert len(result) == 21
    assert {row["id"] for row in result if row["is_used"]} == {used}
    assert len(queries) == 1


def test_unknown_completion_time_has_same_order_on_both_databases(audit_database):
    with audit_database() as db:
        user, template, exercise_id = program(db)
        source = db.get(Exercise, exercise_id)
        known = []
        for offset, weight in enumerate([80, 60, 40, 200]):
            day = START - timedelta(days=7 * offset)
            session = WorkoutSession(user_id=user.telegram_id, template_id=template.id,
                                     template_name=template.name, muscle_group="Грудь", scheduled_date=day,
                                     actual_date=day, status="completed", phase=1, phase_type="accumulation",
                                     completed_at=datetime.combine(day, datetime.min.time(), timezone.utc) if offset < 3 else None)
            db.add(session); db.flush()
            item = SessionExercise(session_id=session.id, exercise_id=exercise_id, movement_id=source.movement_id,
                                   name="Synthetic", kind="strength", position=0, sets_count=1,
                                   target_weight=weight, target_reps=8, min_reps=6, max_reps=12, primary_group="Грудь")
            db.add(item); db.flush()
            db.add(SetResult(session_exercise_id=item.id, set_index=1, weight=weight, reps=8,
                             rir_reported=2, is_working=True))
            if offset < 3:
                known.append(session.id)
        db.commit(); db.expire_all()
        assert [item.session_id for item in latest_accumulation(db, exercise_id)] == known
        weight, reps, _ = prescription(db, db.get(Exercise, exercise_id), SimpleNamespace(phase_type="accumulation"), False)
        assert (weight, reps) == (60, 9)


def test_completion_order_keeps_timezone_offsets_and_unknown_dates():
    first = datetime.fromisoformat("2026-11-01T01:50:00-04:00")
    second = datetime.fromisoformat("2026-11-01T01:20:00-05:00")
    assert completion_timestamp(first) < completion_timestamp(second)
    assert completion_timestamp(second) == completion_timestamp(datetime.fromisoformat("2026-11-01T06:20:00"))
    assert completion_timestamp(None) < completion_timestamp(first)


def test_vacation_priority_cannot_be_bypassed_by_legacy_deload(audit_database, audit_http, clock):
    headers = signed_header(1001, clock)
    later = START + timedelta(days=7)
    with audit_database() as db:
        user, template, _ = program(db)
        session = get_or_create_session(db, template, START)
        template_id, session_id = template.id, session.id
    assert audit_http.put('/api/next-week', json={'kind': 'vacation'}, headers=headers).status_code == 200
    # Reproduce a retained inconsistency from the old legacy route, without
    # rewriting it as part of the fix or altering the original workout.
    with audit_database() as db:
        saved = resolve_week(db, 1001, later)
        saved.phase_type, saved.target_rir = 'deload', 4
        db.commit()
    assert audit_http.post(f'/api/weeks/{later}/manual-deload', headers=headers).status_code == 409
    clock.set(datetime.combine(later, datetime.min.time(), timezone.utc) + timedelta(hours=12))
    headers = signed_header(1001, clock)
    result = audit_http.get(f'/api/templates/{template_id}/preview', params={'on_date': later.isoformat()}, headers=headers)
    assert result.status_code == 200
    assert result.json()['state'] == 'blocked'
    assert result.json()['week']['phase_type'] == 'vacation'
    assert audit_http.post(f'/api/templates/{template_id}/start', headers=headers).status_code == 409
    assert audit_http.patch(f'/api/sessions/{session_id}/reschedule', json={'scheduled_date': later.isoformat()}, headers=headers).status_code == 409
    with audit_database() as db:
        session = db.get(WorkoutSession, session_id)
        assert session.scheduled_date == START and session.status == 'planned'
        assert db.scalar(select(func.count()).select_from(WorkoutSession)) == 1
        saved = db.scalar(select(TrainingWeek).where(TrainingWeek.week_start == later))
        assert saved.phase_type == 'deload'  # No retroactive repair of saved data.


@pytest.mark.parametrize('cancelled', [False, True])
def test_vacation_completion_respects_explicit_prior_cancel(audit_database, audit_http, clock, cancelled):
    with audit_database() as db:
        user, template, _ = program(db)
        session = get_or_create_session(db, template, START)
        session_id = session.id
        item_id = session.exercises[0].id
        for index in (1, 2):
            save_set(item_id, index, ResultIn(weight=80, reps=8, rir_reported=2), user, db)
            db.expire_all()
    headers = signed_header(1001, clock)
    assert audit_http.put('/api/next-week', json={'kind':'vacation'}, headers=headers).status_code == 200
    if cancelled:
        assert audit_http.delete('/api/next-week', headers=headers).status_code == 200
    later = START + timedelta(days=7)
    clock.set(datetime.combine(later, datetime.min.time(), timezone.utc) + timedelta(hours=12))
    headers = signed_header(1001, clock)
    assert audit_http.post(f'/api/sessions/{session_id}/complete', headers=headers).status_code == (200 if cancelled else 409)
    with audit_database() as db:
        session = db.get(WorkoutSession, session_id)
        assert session.status == ('completed' if cancelled else 'in_progress')
        assert session.actual_date == (later if cancelled else None)
        assert db.scalar(select(func.count()).select_from(SetResult)) == 2


def test_timezone_change_cannot_rewrite_an_already_completed_actual_week(audit_database, clock):
    with audit_database() as db:
        user, template, _ = program(db)
        session = get_or_create_session(db, template, START)
        item_id = session.exercises[0].id
        for index in (1, 2):
            save_set(item_id, index, ResultIn(weight=80, reps=8, rir_reported=2), user, db)
            db.expire_all()
        user.timezone = 'Pacific/Kiritimati'
        db.commit()
        clock.set(datetime(2026, 11, 1, 10, 30, tzinfo=timezone.utc))
        assert complete_session(session.id, user, db)['actual_date'] == '2026-11-02'
        user.timezone = 'America/Los_Angeles'
        db.commit()
        with pytest.raises(HTTPException) as error:
            set_next_week(NextWeekIn(kind='vacation'), user, db)
        assert error.value.status_code == 409


def test_movement_kind_cannot_race_its_first_assignment(audit_database):
    with audit_database() as db:
        user, template, _ = program(db)
        unused = Movement(user_id=1001, name='Unused synthetic', kind='strength', primary_group='Грудь')
        db.add(unused); db.commit()
        movement_id, template_id = unused.id, template.id
    engine = audit_database.kw['bind']
    checked_unused, assignment_finished = Event(), Event()

    def after_check(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith('SELECT') and 'EXISTS' in statement.upper() and 'set_results' not in statement and 'session_exercises' in statement:
            checked_unused.set()
            assignment_finished.wait(.4)

    event.listen(engine, 'after_cursor_execute', after_check)

    def change_kind():
        with audit_database() as db:
            try:
                update_movement(movement_id, MovementIn(name='Unused synthetic', kind='cardio'), db.get(User,1001), db)
                return 200
            except HTTPException as exc:
                return exc.status_code

    def assign():
        assert checked_unused.wait(5)
        with audit_database() as db:
            try:
                create_exercise(template_id, ExerciseIn(name='Unused synthetic', movement_id=movement_id), db.get(User,1001), db)
                return 200
            except HTTPException as exc:
                return exc.status_code
            finally:
                assignment_finished.set()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            editing = pool.submit(change_kind)
            assigning = pool.submit(assign)
            outcomes = (editing.result(timeout=10), assigning.result(timeout=10))
    finally:
        event.remove(engine, 'after_cursor_execute', after_check)
    assert outcomes in ((200,422), (409,200))
    with audit_database() as db:
        movement = db.get(Movement,movement_id)
        linked = list(db.scalars(select(Exercise).where(Exercise.movement_id==movement_id)))
        assert movement.kind=='strength' or linked==[]
