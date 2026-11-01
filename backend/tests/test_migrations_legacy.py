"""Migrate a complete synthetic legacy graph twice, including real PostgreSQL."""

import os
from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import Column, ForeignKey, MetaData, Table, UniqueConstraint, create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.db import Base, make_engine
from app.main import history
from app.migrations import migrate
from app.models import User

# Column contract from the original models at 8745307 (before migrations 1–4).
# Types and FK targets for these unchanged legacy fields come from the models.
LEGACY_COLUMNS = {
    "users": "telegram_id chat_id timezone created_at",
    "workout_templates": "id user_id name muscle_group weekday send_time next_phase active",
    "exercises": "id template_id name position sets_count medium_weight weight_step light_factor heavy_factor light_min light_max medium_min medium_max heavy_min heavy_max active",
    "workout_sessions": "id user_id template_id template_name muscle_group scheduled_date phase status created_at completed_at",
    "session_exercises": "id session_id exercise_id name position sets_count target_weight target_reps min_reps max_reps skipped",
    "set_results": "id session_exercise_id set_index weight reps",
    "reminders": "id template_id local_date sent_at message_id",
}


@pytest.fixture(params=["sqlite", "postgresql"])
def legacy_engine(request, tmp_path):
    if request.param == "sqlite":
        engine = make_engine("sqlite:///" + str(tmp_path / "legacy.db"))
        try:
            yield engine
        finally:
            engine.dispose()
        return

    raw_url = os.environ.get("GYMBOT_TEST_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set GYMBOT_TEST_POSTGRES_URL for a disposable loopback gymbot_test database")
    url = make_url(raw_url)
    if (url.get_backend_name() != "postgresql" or url.host not in ("127.0.0.1", "localhost")
            or url.database != "gymbot_test"):
        pytest.fail("PostgreSQL checks accept only a loopback database named gymbot_test", pytrace=False)

    # Each test owns one generated schema. No public or pre-existing schema is
    # migrated or dropped, even if other developers share the local test server.
    schema = "gymbot_stage0_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        yield engine
    finally:
        engine.dispose()
        try:
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        finally:
            admin.dispose()


def seed_legacy(engine):
    metadata = MetaData()
    for table_name, field_names in LEGACY_COLUMNS.items():
        source = Base.metadata.tables[table_name]
        columns = []
        for name in field_names.split():
            column = source.c[name]
            columns.append(Column(
                name, column.type,
                *(ForeignKey(foreign.target_fullname) for foreign in column.foreign_keys),
                primary_key=column.primary_key, nullable=column.nullable,
            ))
        unique = [UniqueConstraint(*(column.name for column in constraint.columns))
                  for constraint in source.constraints if isinstance(constraint, UniqueConstraint)]
        Table(table_name, metadata, *columns, *unique)
    metadata.create_all(engine)
    moment = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
    with engine.begin() as connection:
        connection.execute(metadata.tables["users"].insert(), {
            "telegram_id": 9001, "chat_id": None, "timezone": "Europe/Moscow", "created_at": moment,
        })
        connection.execute(metadata.tables["workout_templates"].insert(), {
            "id": "legacy-day", "user_id": 9001, "name": "Старый день", "muscle_group": "Грудь",
            "weekday": 0, "send_time": "09:00", "next_phase": 1, "active": True,
        })
        connection.execute(metadata.tables["exercises"].insert(), {
            "id": "legacy-exercise", "template_id": "legacy-day", "name": "Старый жим",
            "position": 0, "sets_count": 2, "medium_weight": 50, "weight_step": 2.5,
            "light_factor": 0.9, "heavy_factor": 1.05, "light_min": 12, "light_max": 15,
            "medium_min": 8, "medium_max": 12, "heavy_min": 6, "heavy_max": 8, "active": True,
        })
        connection.execute(metadata.tables["workout_sessions"].insert(), {
            "id": "legacy-session", "user_id": 9001, "template_id": "legacy-day",
            "template_name": "Старый день", "muscle_group": "Грудь", "scheduled_date": date(2026, 10, 19),
            "phase": 1, "status": "completed", "created_at": moment, "completed_at": moment,
        })
        connection.execute(metadata.tables["session_exercises"].insert(), {
            "id": "legacy-snapshot", "session_id": "legacy-session", "exercise_id": "legacy-exercise",
            "name": "Историческое название", "position": 0, "sets_count": 2, "target_weight": 50,
            "target_reps": 8, "min_reps": 8, "max_reps": 12, "skipped": False,
        })
        connection.execute(metadata.tables["set_results"].insert(), [
            {"id": "legacy-set-1", "session_exercise_id": "legacy-snapshot", "set_index": 1, "weight": 50, "reps": 8},
            {"id": "legacy-set-2", "session_exercise_id": "legacy-snapshot", "set_index": 2, "weight": 47.5, "reps": 10},
        ])
        connection.execute(metadata.tables["reminders"].insert(), {
            "id": "legacy-reminder", "template_id": "legacy-day", "local_date": date(2026, 10, 19),
            "sent_at": moment, "message_id": None,
        })
    return metadata


def legacy_rows(engine, metadata):
    with engine.connect() as connection:
        return {table.name: [tuple(row) for row in connection.execute(
            select(table).order_by(*table.primary_key.columns)
        )] for table in metadata.sorted_tables}


def test_complete_legacy_graph_survives_migration_and_reapplication(legacy_engine):
    metadata = seed_legacy(legacy_engine)
    before = legacy_rows(legacy_engine, metadata)
    for _ in range(2):
        migrate(legacy_engine)
        assert legacy_rows(legacy_engine, metadata) == before
        with legacy_engine.connect() as connection:
            assert list(connection.execute(text("SELECT version FROM schema_versions ORDER BY version")).scalars()) == [1, 2, 3, 4]
            assert list(connection.execute(text("SELECT rir_reported, rir_target FROM set_results"))) == [(None, None), (None, None)]
            assert connection.execute(text("SELECT movement_id FROM session_exercises")).scalar() is None
            assert connection.execute(text("SELECT actual_date FROM workout_sessions")).scalar() is None
            assert connection.execute(text("SELECT SUM(weight * reps) FROM set_results")).scalar() == 875
        assert "duration_minutes" in {column["name"] for column in inspect(legacy_engine).get_columns("exercises")}
        with Session(legacy_engine) as db:
            recorded = history(db.get(User, 9001), db)
            assert len(recorded) == 1
            assert recorded[0]["exercises"][0]["name"] == "Историческое название"
            assert [row["weight"] for row in recorded[0]["exercises"][0]["results"]] == [50, 47.5]
