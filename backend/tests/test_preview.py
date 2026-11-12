"""Preview contracts: real read-only transactions, owned synthetic data only."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import Event, Thread, get_ident
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, inspect, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app import auth, main
from app.db import Base, get_db
from app.main import change_sets_count, create_template, override_target, session_detail
from app.models import Exercise, TrainingWeek, User, WeekOverride, WorkoutTemplate
from app.planning import get_or_create_session, resolve_week
from app.schemas import OverrideIn, SetsCountIn, TemplateIn
from test_history import START, program, replace
from test_recommendations import on_day, record
from test_replacement_http import TEST_TOKEN, signed_header


@pytest.fixture(params=["sqlite", "postgresql"])
def preview_database(request):
    return request.getfixturevalue("database" if request.param == "sqlite" else "postgres_database")


@pytest.fixture
def preview_http(preview_database, clock, monkeypatch):
    def database_dependency():
        with preview_database() as db:
            yield db

    verify = auth.verify_init_data
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(
        app_env="development", bot_token=TEST_TOKEN, dev_telegram_id=0,
    ))
    monkeypatch.setattr(auth, "verify_init_data", lambda raw, token: verify(
        raw, token, now=int(clock.moment.timestamp()),
    ))
    main.app.dependency_overrides[get_db] = database_dependency
    # No TestClient context manager: app lifespan, bot, migration and reminder
    # startup must not run against any application-configured engine.
    client = TestClient(main.app)
    try:
        yield client
    finally:
        client.close()
        main.app.dependency_overrides.pop(get_db, None)


def setup(preview_database, kind="strength"):
    with preview_database() as db:
        user, template, exercise_id = program(db, kind)
        exercise = db.get(Exercise, exercise_id)
        exercise.medium_weight, exercise.sets_count = 60, 3
        db.commit()
        return user.telegram_id, template.id, exercise_id


def database_rows(factory):
    """Every mapped table plus the migration registry, including NULL values."""
    with factory() as db:
        tables = set(inspect(db.bind).get_table_names())
        assert tables == {*Base.metadata.tables, "schema_versions"}
        rows = {table.name: sorted((tuple(row) for row in db.execute(select(table))), key=repr)
                for table in Base.metadata.sorted_tables}
        rows["schema_versions"] = list(db.execute(text("SELECT version FROM schema_versions ORDER BY version")))
        assert rows["schema_versions"][-1] == (9,)
        return rows


@contextmanager
def forbid_writes(factory, monkeypatch):
    statements = []

    def audit(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)
        first = statement.lstrip().split(None, 1)[0].upper()
        assert first not in {"INSERT", "UPDATE", "DELETE", "REPLACE", "MERGE", "CREATE", "ALTER", "DROP", "TRUNCATE"}, statement
        assert "FOR UPDATE" not in statement.upper(), statement

    def forbidden(*args, **kwargs):
        pytest.fail("Preview called Session.flush/commit instead of computing in memory")

    engine = factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", audit)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(Session, "flush", forbidden)
            patch.setattr(Session, "commit", forbidden)
            yield statements
    finally:
        event.remove(engine, "before_cursor_execute", audit)


def read_preview(client, factory, clock, monkeypatch, template_id, on_date=START,
                 user_id=1001, status=200, extra_headers=None):
    before = database_rows(factory)
    headers = signed_header(user_id, clock) if extra_headers is None else extra_headers
    path = f"/api/templates/{template_id}/preview"
    params = {} if on_date is None else {"on_date": on_date.isoformat() if hasattr(on_date, "isoformat") else on_date}
    with forbid_writes(factory, monkeypatch):
        response = client.get(path, params=params, headers=headers)
    assert response.status_code == status, response.text
    assert database_rows(factory) == before
    if status == 200:
        body = response.json()
        assert body["provisional"] is True
        assert body["persisted"] is False
        assert body["template_id"] == template_id
        assert body["on_date"] == params["on_date"]
        assert body["computed_at"]
        assert "id" not in body and "session_id" not in body
        assert "id" not in (body["week"] or {})
        return body
    return response


def compare_created(factory, clock, template_id, preview, on_date=START):
    """Only after no-write assertions, create on the same unchanged inputs."""
    on_day(clock, on_date)
    with factory() as db:
        template = db.get(WorkoutTemplate, template_id)
        actual = get_or_create_session(db, template, on_date)
        assert actual is not None
        assert actual.week.week_number == preview["week"]["week_number"]
        assert actual.phase_type == preview["week"]["phase_type"]
        assert actual.week.is_postponed == preview["week"]["is_postponed"]
        assert len(actual.exercises) == len(preview["exercises"])
        saved_rows = {row["exercise_id"]: row for row in session_detail(actual.id, db.get(User, 1001), db)["exercises"]}
        for calculated, saved in zip(preview["exercises"], actual.exercises):
            assert calculated["exercise_id"] == saved.exercise_id
            assert calculated["movement_id"] == saved.movement_id
            assert calculated["kind"] == saved.kind
            if saved.kind == "strength":
                assert (calculated["target_weight"], calculated["target_reps"], calculated["sets_count"], calculated["target_rir"]) == (
                    float(saved.target_weight), saved.target_reps, saved.sets_count, float(saved.target_rir),
                )
                original = saved_rows[saved.exercise_id]["recommendation"]
                expected_context = deepcopy(calculated["recommendation"])
                original.pop("created_at", None)
                expected_context.pop("created_at", None)
                assert expected_context == original
            else:
                assert calculated["target_duration_minutes"] == saved.target_duration_minutes
                assert calculated["target_weight"] is None
                assert calculated["target_reps"] is None
                assert calculated["sets_count"] is None
                assert calculated["target_rir"] is None
                assert calculated["recommendation"] is None


@pytest.mark.parametrize("history,expected", [
    ([], (60, 6)),
    ([([50, 47.5, 45], 8)], (50, 9)),
    ([([60, 55, 50], 12)], (62.5, 6)),
    ([([60, 60, 60], 8), ([60, 60, 60], 8), ([62.5, 62.5, 62.5], 8)], (60, 9)),
])
def test_ready_preview_is_repeatable_read_only_and_matches_creation(preview_database, preview_http, clock, monkeypatch, history, expected):
    _, template_id, exercise_id = setup(preview_database)
    with preview_database() as db:
        user, template = db.get(User, 1001), db.get(WorkoutTemplate, template_id)
        for offset, (weights, reps) in enumerate(history):
            day = START - timedelta(days=7 - offset)
            on_day(clock, day)
            session = get_or_create_session(db, template, day)
            record(db, user, session, weights, reps=reps)
    on_day(clock, START)
    first = read_preview(preview_http, preview_database, clock, monkeypatch, template_id)
    assert first["state"] == "ready"
    assert first["week"]["source"] == "calculated"
    assert first["existing_session"] is None
    assert first["blocking_reasons"] == []
    row = first["exercises"][0]
    assert (row["target_weight"], row["target_reps"]) == expected
    assert row["exercise_id"] == exercise_id
    assert row["slot_id"] == row["history_id"] == exercise_id
    assert "id" not in row and "session_id" not in row
    assert row["recommendation"]["manual_override"] == {}
    assert read_preview(preview_http, preview_database, clock, monkeypatch, template_id) == first
    compare_created(preview_database, clock, template_id, first)


@pytest.mark.parametrize("kind", ["cardio", "stretch", "other_timed"])
def test_timed_preview_has_minutes_without_fictitious_strength_values(preview_database, preview_http, clock, monkeypatch, kind):
    _, template_id, _ = setup(preview_database, kind)
    result = read_preview(preview_http, preview_database, clock, monkeypatch, template_id)
    assert result["state"] == "ready"
    assert result["exercises"][0]["target_duration_minutes"] == 20
    compare_created(preview_database, clock, template_id, result)


def test_timed_only_preview_does_not_need_unrelated_strength_configuration(preview_database, preview_http, clock, monkeypatch):
    _, template_id, _ = setup(preview_database, "cardio")
    with preview_database() as db:
        other = create_template(TemplateIn(name="Старый силовой день", muscle_group="Грудь", weekday=2,
                                           send_time="09:00"), db.get(User, 1001), db)
        db.add(Exercise(template_id=other["id"], name="Несвязанное силовое назначение", movement_id=None,
                        position=0, sets_count=3, medium_weight=10, weight_step=2.5))
        db.commit()
    result = read_preview(preview_http, preview_database, clock, monkeypatch, template_id)
    assert result["state"] == "ready"
    assert result["blocking_reasons"] == []
    assert result["exercises"][0]["target_duration_minutes"] == 20
    assert result["exercises"][0]["target_weight"] is None


@pytest.mark.parametrize("mode,weight", [("new_movement", 20), ("resume", 60), ("new_base", 30)])
def test_preview_keeps_replacement_history_identity(preview_database, preview_http, clock, monkeypatch, mode, weight):
    _, template_id, exercise_id = setup(preview_database)
    with preview_database() as db:
        user, template = db.get(User, 1001), db.get(WorkoutTemplate, template_id)
        movement_a = db.get(Exercise, exercise_id).movement_id
        on_day(clock, START - timedelta(days=7))
        record(db, user, get_or_create_session(db, template, START - timedelta(days=7)), [60, 60, 60])
        replacement_id = replace(db, user, exercise_id, "B", weight=20)
        if mode != "new_movement":
            replacement_id = replace(db, user, replacement_id, "A", weight=30, movement_id=movement_a,
                                     history_mode="resume" if mode == "resume" else "new",
                                     history_id=exercise_id if mode == "resume" else None)
    on_day(clock, START)
    result = read_preview(preview_http, preview_database, clock, monkeypatch, template_id)
    row = result["exercises"][0]
    assert row["exercise_id"] == replacement_id
    assert row["target_weight"] == weight
    assert row["history_id"] == (exercise_id if mode == "resume" else replacement_id)
    compare_created(preview_database, clock, template_id, result)


@pytest.mark.parametrize("status", ["planned", "in_progress", "completed", "replaced"])
def test_existing_session_and_manual_snapshot_are_not_recalculated(preview_database, preview_http, clock, monkeypatch, status):
    _, template_id, exercise_id = setup(preview_database)
    with preview_database() as db:
        user = db.get(User, 1001)
        session = get_or_create_session(db, db.get(WorkoutTemplate, template_id), START)
        override_target(session.exercises[0].id, OverrideIn(target_weight=77.5, target_reps=9), user, db)
        db.expire_all()
        if status == "completed":
            record(db, user, session, [77.5, 77.5, 77.5], reps=9)
        elif status == "in_progress":
            from app.main import save_set
            from app.schemas import ResultIn
            save_set(session.exercises[0].id, 1, ResultIn(weight=77.5, reps=9, rir_reported=0), user, db)
        db.expire_all()
        before = deepcopy(session_detail(session.id, user, db))
        session_id = session.id
        if status == "replaced":
            replace(db, user, exercise_id, "Новое B вместо открытого A", weight=20)
        db.get(Exercise, exercise_id).medium_weight = 100
        db.commit()
    requested = START if status == "completed" else START + timedelta(days=1)
    result = read_preview(preview_http, preview_database, clock, monkeypatch, template_id, requested)
    assert result["state"] == "existing"
    assert result["exercises"] == []
    assert result["existing_session"] == {"id": session_id, "scheduled_date": START.isoformat(),
                                          "status": "planned" if status == "replaced" else status}
    with preview_database() as db:
        assert session_detail(session_id, db.get(User, 1001), db) == before


def test_saved_week_targets_remain_the_source_instead_of_current_settings(preview_database, preview_http, clock, monkeypatch):
    _, template_id, _ = setup(preview_database)
    with preview_database() as db:
        week = resolve_week(db, 1001, START)
        week.targets_json = '{"Грудь": [1, 2, 2]}'
        db.get(User, 1001).volume_cap = 20
        db.commit()
    result = read_preview(preview_http, preview_database, clock, monkeypatch, template_id)
    assert result["week"]["source"] == "saved"
    assert result["exercises"][0]["sets_count"] == 2
    compare_created(preview_database, clock, template_id, result)


@pytest.mark.parametrize("missed", [False, True])
def test_projected_missed_deload_is_used_without_updating_the_old_week(preview_database, preview_http, clock, monkeypatch, missed):
    _, template_id, _ = setup(preview_database)
    with preview_database() as db:
        user, template = db.get(User, 1001), db.get(WorkoutTemplate, template_id)
        for weeks_ago in (3, 2):
            day = START - timedelta(weeks=weeks_ago)
            on_day(clock, day)
            session = get_or_create_session(db, template, day)
            # Keep both comparison weeks at three completed sets, despite the
            # ordinary weekly progression that can add a fourth set.
            change_sets_count(session.exercises[0].id, SetsCountIn(sets_count=3), user, db)
            db.expire_all()
            record(db, user, session, [60] * 3)
        day = START - timedelta(weeks=1)
        on_day(clock, day)
        week = resolve_week(db, 1001, day)
        week.phase_type, week.target_rir, week.missed_deload = "deload", 4, False
        db.commit()
        session = get_or_create_session(db, template, day)
        change_sets_count(session.exercises[0].id, SetsCountIn(sets_count=3 if missed else 2), user, db)
        db.expire_all()
        record(db, user, session, [60] * (3 if missed else 2), rir=4)
        prior_id = week.id
        assert db.get(TrainingWeek, prior_id).missed_deload is False
    on_day(clock, START)
    result = read_preview(preview_http, preview_database, clock, monkeypatch, template_id)
    assert result["state"] == "ready"
    assert result["week"]["week_number"] == (4 if missed else 1)
    assert result["exercises"][0]["target_rir"] == (2 if missed else 2.5)
    with preview_database() as db:
        assert db.get(TrainingWeek, prior_id).missed_deload is False
    compare_created(preview_database, clock, template_id, result)
    with preview_database() as db:
        assert db.get(TrainingWeek, prior_id).missed_deload is missed


@pytest.mark.parametrize("mode", ["manual", "scheduled", "fatigue", "long_break"])
def test_unsaved_phase_decision_matches_creation(preview_database, preview_http, clock, monkeypatch, mode):
    _, template_id, _ = setup(preview_database)
    with preview_database() as db:
        user, template = db.get(User, 1001), db.get(WorkoutTemplate, template_id)
        if mode == "manual":
            db.add(WeekOverride(user_id=1001, week_start=START, kind="deload"))
            db.commit()
        else:
            weeks = (3, 2, 1) if mode == "scheduled" else (6,) if mode == "long_break" else (1,)
            for weeks_ago in weeks:
                day = START - timedelta(weeks=weeks_ago)
                on_day(clock, day)
                session = get_or_create_session(db, template, day)
                record(db, user, session, [60] * session.exercises[0].sets_count,
                       rir=0.5 if mode == "fatigue" else 1.5 if mode == "scheduled" else 2)
    on_day(clock, START)
    result = read_preview(preview_http, preview_database, clock, monkeypatch, template_id)
    assert result["week"]["phase_type"] == ("accumulation" if mode == "long_break" else "deload")
    assert result["exercises"][0]["target_rir"] == (2 if mode == "long_break" else 4)
    compare_created(preview_database, clock, template_id, result)


@pytest.mark.parametrize("has_existing", [False, True])
def test_vacation_is_blocked_without_materializing_week_or_cycle(preview_database, preview_http, clock, monkeypatch, has_existing):
    _, template_id, _ = setup(preview_database)
    with preview_database() as db:
        if has_existing:
            get_or_create_session(db, db.get(WorkoutTemplate, template_id), START)
        db.add(WeekOverride(user_id=1001, week_start=START + timedelta(weeks=1), kind="vacation"))
        db.commit()
    result = read_preview(preview_http, preview_database, clock, monkeypatch, template_id, START + timedelta(weeks=1))
    assert result["state"] == "blocked"
    assert result["week"]["phase_type"] == "vacation"
    assert result["exercises"] == []
    assert any(item["code"] == "vacation" for item in result["blocking_reasons"])


@pytest.mark.parametrize("problem", ["empty", "target_movement", "other_day_movement"])
def test_incomplete_program_is_blocked_without_repairing_it(preview_database, preview_http, clock, monkeypatch, problem):
    _, template_id, exercise_id = setup(preview_database)
    with preview_database() as db:
        if problem == "empty":
            db.get(Exercise, exercise_id).active = False
        elif problem == "target_movement":
            db.get(Exercise, exercise_id).movement_id = None
        else:
            other = create_template(TemplateIn(name="Другой синтетический день", muscle_group="Грудь", weekday=2,
                                               send_time="09:00"), db.get(User, 1001), db)
            db.add(Exercise(template_id=other["id"], name="Старое несвязанное назначение", movement_id=None,
                            position=0, sets_count=3, medium_weight=10, weight_step=2.5))
        db.commit()
    result = read_preview(preview_http, preview_database, clock, monkeypatch, template_id)
    assert result["state"] == "blocked"
    assert result["exercises"] == []
    assert result["blocking_reasons"]
    assert all(item["code"] and item["message"] for item in result["blocking_reasons"])


def test_changing_or_cancelling_override_recomputes_without_leaving_draft_weeks(preview_database, preview_http, clock, monkeypatch):
    _, template_id, _ = setup(preview_database)
    target = START + timedelta(weeks=1)
    with preview_database() as db:
        override = WeekOverride(user_id=1001, week_start=target, kind="vacation")
        db.add(override)
        db.commit()
        override_id = override.id
    result = read_preview(preview_http, preview_database, clock, monkeypatch, template_id, target)
    assert result["state"] == "blocked" and result["week"]["phase_type"] == "vacation"
    with preview_database() as db:
        db.get(WeekOverride, override_id).kind = "deload"
        db.commit()
    result = read_preview(preview_http, preview_database, clock, monkeypatch, template_id, target)
    assert result["state"] == "ready" and result["exercises"][0]["target_rir"] == 4
    with preview_database() as db:
        db.delete(db.get(WeekOverride, override_id))
        db.commit()
    result = read_preview(preview_http, preview_database, clock, monkeypatch, template_id, target)
    assert result["state"] == "ready" and result["exercises"][0]["target_rir"] == 2
    with preview_database() as db:
        assert list(db.scalars(select(TrainingWeek))) == []


def test_another_users_unconfigured_program_does_not_block_the_owner(preview_database, preview_http, clock, monkeypatch):
    _, template_id, _ = setup(preview_database)
    with preview_database() as db:
        other = User(telegram_id=2002)
        db.add(other)
        db.commit()
        template = create_template(TemplateIn(name="Чужой синтетический день", muscle_group="Грудь", weekday=1,
                                              send_time="09:00"), other, db)
        db.add(Exercise(template_id=template["id"], name="Чужое несвязанное назначение", movement_id=None,
                        position=0, sets_count=3, medium_weight=10, weight_step=2.5))
        db.commit()
    result = read_preview(preview_http, preview_database, clock, monkeypatch, template_id)
    assert result["state"] == "ready"
    assert result["blocking_reasons"] == []
    assert result["exercises"][0]["target_weight"] == 60


@pytest.mark.parametrize("on_date,status", [(None, 422), ("not-a-date", 422),
                                            (START - timedelta(days=1), 422),
                                            (START + timedelta(days=14), 422),
                                            (START + timedelta(days=13), 200)])
def test_explicit_date_and_bounded_horizon(preview_database, preview_http, clock, monkeypatch, on_date, status):
    _, template_id, _ = setup(preview_database)
    read_preview(preview_http, preview_database, clock, monkeypatch, template_id, on_date, status=status)


@pytest.mark.parametrize("zone,today,last_allowed", [("Europe/Moscow", "2026-10-26", "2026-11-08"),
                                                      ("America/New_York", "2026-10-25", "2026-11-01")])
def test_horizon_uses_the_users_local_sunday_monday_boundary(preview_database, preview_http, clock, monkeypatch, zone, today, last_allowed):
    _, template_id, _ = setup(preview_database)
    with preview_database() as db:
        db.get(User, 1001).timezone = zone
        db.commit()
    clock.set(datetime(2026, 10, 25, 22, 30, tzinfo=timezone.utc))
    result = read_preview(preview_http, preview_database, clock, monkeypatch, template_id, today)
    assert result["timezone"] == zone
    read_preview(preview_http, preview_database, clock, monkeypatch, template_id, last_allowed)
    from datetime import date
    beyond = date.fromisoformat(last_allowed) + timedelta(days=1)
    read_preview(preview_http, preview_database, clock, monkeypatch, template_id, beyond, status=422)


def test_authentication_and_ownership_never_bootstrap_an_unknown_user(preview_database, preview_http, clock, monkeypatch):
    _, template_id, _ = setup(preview_database)
    read_preview(preview_http, preview_database, clock, monkeypatch, template_id, user_id=2002, status=404)
    read_preview(preview_http, preview_database, clock, monkeypatch, template_id, extra_headers={}, status=401)
    expired = signed_header(1001, clock, auth_date=int(clock.moment.timestamp()) - 86401)
    read_preview(preview_http, preview_database, clock, monkeypatch, template_id, extra_headers=expired, status=401)
    valid = signed_header(1001, clock)
    tampered = {"Authorization": valid["Authorization"].replace("1001", "2002")}
    read_preview(preview_http, preview_database, clock, monkeypatch, template_id, extra_headers=tampered, status=401)
    with preview_database() as db:
        assert db.get(User, 2002) is None
        db.add(User(telegram_id=2002))
        db.commit()
    read_preview(preview_http, preview_database, clock, monkeypatch, template_id, user_id=2002, status=404)
    with preview_database() as db:
        db.get(WorkoutTemplate, template_id).active = False
        db.commit()
    read_preview(preview_http, preview_database, clock, monkeypatch, template_id, status=404)
    read_preview(preview_http, preview_database, clock, monkeypatch, "unknown-template", status=404)


def test_development_header_is_still_restricted_to_the_configured_identity(preview_database, preview_http, clock, monkeypatch):
    _, template_id, _ = setup(preview_database)
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(
        app_env="development", bot_token=TEST_TOKEN, dev_telegram_id=1001,
    ))
    read_preview(preview_http, preview_database, clock, monkeypatch, template_id,
                 extra_headers={"X-Dev-User-Id": "1001"})
    read_preview(preview_http, preview_database, clock, monkeypatch, template_id,
                 extra_headers={"X-Dev-User-Id": "2002"}, status=401)
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(
        app_env="production", bot_token=TEST_TOKEN, dev_telegram_id=1001,
    ))
    read_preview(preview_http, preview_database, clock, monkeypatch, template_id,
                 extra_headers={"X-Dev-User-Id": "1001"}, status=401)


def test_database_read_only_guard_and_pool_reset_after_failure(preview_database):
    from app.db import readonly_transaction

    setup(preview_database)
    with preview_database() as db:
        with readonly_transaction(db):
            if db.bind.dialect.name == "postgresql":
                assert db.execute(text("SHOW transaction_read_only")).scalar() == "on"
                assert db.execute(text("SHOW transaction_isolation")).scalar() == "repeatable read"
            else:
                assert db.execute(text("PRAGMA query_only")).scalar() == 1
            assert db.get(User, 1001) is not None
    with preview_database() as db:
        with readonly_transaction(db):
            with pytest.raises(DBAPIError):
                db.execute(text("UPDATE users SET volume_cap = 19 WHERE telegram_id = 1001"))
    with preview_database() as db:
        assert db.get(User, 1001).volume_cap == 20
        db.get(User, 1001).volume_cap = 18
        db.commit()
    with preview_database() as db:
        assert db.get(User, 1001).volume_cap == 18


def test_postgresql_preview_uses_one_coherent_snapshot_during_concurrent_edit(postgres_database, clock, monkeypatch):
    """A committed writer between reader queries cannot produce a hybrid plan."""
    setup(postgres_database)
    with postgres_database() as db:
        template_id = db.scalar(select(WorkoutTemplate.id))
        exercise_id = db.scalar(select(Exercise.id))
    verify = auth.verify_init_data
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(app_env="development", bot_token=TEST_TOKEN, dev_telegram_id=0))
    monkeypatch.setattr(auth, "verify_init_data", lambda raw, token: verify(raw, token, now=int(clock.moment.timestamp())))

    def dependency():
        with postgres_database() as db:
            yield db

    main.app.dependency_overrides[get_db] = dependency
    first_read, committed = Event(), Event()
    main_thread = get_ident()
    writer_ident = []
    failures = []

    def writer():
        writer_ident.append(get_ident())
        try:
            assert first_read.wait(10)
            with postgres_database() as db:
                db.get(Exercise, exercise_id).medium_weight = 100
                db.commit()
        except BaseException as error:
            failures.append(error)
        finally:
            committed.set()

    def after_read(connection, cursor, statement, parameters, context, executemany):
        if (not first_read.is_set() and get_ident() != main_thread and get_ident() not in writer_ident
                and statement.lstrip().upper().startswith("SELECT")):
            first_read.set()
            assert committed.wait(10)

    engine = postgres_database.kw["bind"]
    worker = Thread(target=writer)
    client = TestClient(main.app)
    event.listen(engine, "after_cursor_execute", after_read)
    worker.start()
    try:
        response = client.get(f"/api/templates/{template_id}/preview", params={"on_date": START.isoformat()},
                              headers=signed_header(1001, clock))
        assert response.status_code == 200, response.text
        assert response.json()["exercises"][0]["target_weight"] == 60
        assert committed.is_set() and not failures
        repeated = client.get(f"/api/templates/{template_id}/preview", params={"on_date": START.isoformat()},
                              headers=signed_header(1001, clock))
        assert repeated.json()["exercises"][0]["target_weight"] == 100
    finally:
        worker.join(12)
        event.remove(engine, "after_cursor_execute", after_read)
        client.close()
        main.app.dependency_overrides.pop(get_db, None)
    assert not worker.is_alive()
