"""Migrate a complete synthetic legacy graph twice, including real PostgreSQL."""

import json
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import Column, ForeignKey, Index, MetaData, Table, UniqueConstraint, inspect, select, text
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateIndex, CreateTable

from app.db import Base, make_engine
from app.main import history
from app.migrations import migrate
from app.models import Exercise, User

# Column contract from the original models at 8745307 (before migrations 1–6).
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

    yield request.getfixturevalue("postgres_engine")


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
        target = Table(table_name, metadata, *columns, *unique)
        # Retain the original indexes on legacy columns; the new slot/history
        # indexes do not belong to the pre-progression schema.
        for index in source.indexes:
            if all(column.name in target.c for column in index.columns):
                Index(index.name, *(target.c[column.name] for column in index.columns), unique=index.unique)
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


def normalized(value):
    if isinstance(value, dict):
        return tuple(sorted((key, normalized(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(normalized(item) for item in value)
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    return str(value)


def index_signature(engine):
    inspector = inspect(engine)
    return {name: tuple(normalized(item) for item in sorted(inspector.get_indexes(name), key=lambda item: item["name"]))
            for name in inspector.get_table_names()}


def schema_signature(engine):
    inspector = inspect(engine)
    return {name: {
        "columns": tuple((column["name"], str(column["type"]), getattr(column["type"], "timezone", None),
                          column["nullable"], normalized(column.get("default")), normalized(column.get("computed")),
                          normalized(column.get("identity"))) for column in inspector.get_columns(name)),
        "primary_key": normalized(inspector.get_pk_constraint(name)),
        "foreign_keys": tuple(sorted((normalized(item) for item in inspector.get_foreign_keys(name)), key=str)),
        "unique": tuple(sorted((normalized(item) for item in inspector.get_unique_constraints(name)), key=str)),
        "checks": tuple(sorted((normalized(item) for item in inspector.get_check_constraints(name)), key=str)),
    } for name in inspector.get_table_names()}


def save_sql_backup(engine, metadata, path):
    """A recoverable SQL backup of these synthetic tables, before migration."""
    statements = [str(CreateTable(table).compile(dialect=engine.dialect))
                  for table in metadata.sorted_tables]
    with engine.connect() as connection:
        for table in metadata.sorted_tables:
            for row in connection.execute(select(table).order_by(*table.primary_key.columns)).mappings():
                statements.append(str(table.insert().values(**dict(row)).compile(
                    dialect=engine.dialect, compile_kwargs={"literal_binds": True},
                )))
    for table in metadata.sorted_tables:
        for index in sorted(table.indexes, key=lambda item: item.name or ""):
            statements.append(str(CreateIndex(index).compile(dialect=engine.dialect)))
    path.write_text(json.dumps(statements, ensure_ascii=False), encoding="utf-8")


def restore_sql_backup(engine, path):
    # Both engines are freshly created test resources; PostgreSQL uses only its
    # generated schema. No public/pre-existing schema or external data is touched.
    Base.metadata.drop_all(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS schema_versions"))
        for statement in json.loads(path.read_text(encoding="utf-8")):
            connection.exec_driver_sql(statement)


def test_complete_legacy_graph_survives_migration_and_reapplication(legacy_engine, tmp_path):
    metadata = seed_legacy(legacy_engine)
    before = legacy_rows(legacy_engine, metadata)
    schema_before, indexes_before = schema_signature(legacy_engine), index_signature(legacy_engine)
    assert any(indexes_before.values())
    backup_path = tmp_path / "synthetic-legacy-backup.sql.json"
    save_sql_backup(legacy_engine, metadata, backup_path)
    for _ in range(2):
        migrate(legacy_engine)
        assert legacy_rows(legacy_engine, metadata) == before
        with legacy_engine.connect() as connection:
            assert list(connection.execute(text("SELECT version FROM schema_versions ORDER BY version")).scalars()) == list(range(1, 10))
            assert list(connection.execute(text("SELECT rir_reported, rir_target FROM set_results"))) == [(None, None), (None, None)]
            assert connection.execute(text("SELECT movement_id FROM session_exercises")).scalar() is None
            assert connection.execute(text("SELECT actual_date FROM workout_sessions")).scalar() is None
            assert connection.execute(text("SELECT SUM(weight * reps) FROM set_results")).scalar() == 875
            assert tuple(connection.execute(text("SELECT slot_id, history_id FROM exercises")).one()) == ("legacy-exercise", "legacy-exercise")
            assert connection.execute(text("SELECT weight_step FROM session_exercises")).scalar() is None
            assert connection.execute(text("SELECT recommendation_context_json FROM session_exercises")).scalar() is None
        assert "duration_minutes" in {column["name"] for column in inspect(legacy_engine).get_columns("exercises")}
        with Session(legacy_engine) as db:
            recorded = history(db.get(User, 9001), db)
            assert len(recorded) == 1
            assert recorded[0]["exercises"][0]["name"] == "Историческое название"
            assert [row["weight"] for row in recorded[0]["exercises"][0]["results"]] == [50, 47.5]
    restore_sql_backup(legacy_engine, backup_path)
    assert legacy_rows(legacy_engine, metadata) == before
    assert schema_signature(legacy_engine) == schema_before
    assert index_signature(legacy_engine) == indexes_before
    assert "schema_versions" not in inspect(legacy_engine).get_table_names()
    assert "slot_id" not in {column["name"] for column in inspect(legacy_engine).get_columns("exercises")}
    for _ in range(2):
        migrate(legacy_engine)
        assert legacy_rows(legacy_engine, metadata) == before


def test_version_four_upgrade_preserves_existing_facts_and_unknown_step(legacy_engine, tmp_path):
    from app.main import create_exercise, update_exercise
    from app.planning import get_or_create_session
    from app.schemas import ExerciseIn
    from app.serializers import exercise_dict
    from test_history import START, finish, program

    migrate(legacy_engine)
    with Session(legacy_engine, expire_on_commit=False) as db:
        user, template, source_id = program(db)
        # These are real current-format rows first; removing only the three new
        # columns below gives a faithful v4 shape without fabricated old values.
        source = db.get(Exercise, source_id)
        session = get_or_create_session(db, template, START)
        finish(db, user, session)
        values = exercise_dict(source)
        for field in ("id", "slot_id", "history_id"):
            values.pop(field, None)
        values["weight_step"] = 5
        update_exercise(source_id, ExerciseIn(**values), user, db)
        create_exercise(template.id, ExerciseIn(name="Ещё одно место", movement_id=source.movement_id,
                                                position=4, medium_weight=30), user, db)
    dialect = legacy_engine.dialect.identifier_preparer
    indexes = [item["name"] for item in inspect(legacy_engine).get_indexes("exercises")
               if {"slot_id", "history_id"}.intersection(item["column_names"])]
    with legacy_engine.begin() as connection:
        for index in indexes:
            connection.execute(text("DROP INDEX " + dialect.quote(index)))
        connection.execute(text("ALTER TABLE exercises DROP COLUMN slot_id"))
        connection.execute(text("ALTER TABLE exercises DROP COLUMN history_id"))
        connection.execute(text("ALTER TABLE session_exercises DROP COLUMN weight_step"))
        connection.execute(text("ALTER TABLE session_exercises DROP COLUMN recommendation_context_json"))
        connection.execute(text("DELETE FROM schema_versions WHERE version >= 5"))
    backup_metadata = MetaData()
    backup_metadata.reflect(legacy_engine)
    complete_before = legacy_rows(legacy_engine, backup_metadata)
    schema_before, indexes_before = schema_signature(legacy_engine), index_signature(legacy_engine)
    assert any(indexes_before.values())
    backup_path = tmp_path / "synthetic-v4-backup.sql.json"
    save_sql_backup(legacy_engine, backup_metadata, backup_path)
    old_metadata = MetaData()
    for table in backup_metadata.sorted_tables:
        if table.name != "schema_versions":
            table.to_metadata(old_metadata)
    before = legacy_rows(legacy_engine, old_metadata)
    for phase in ("upgrade", "restored-upgrade"):
        if phase == "restored-upgrade":
            restore_sql_backup(legacy_engine, backup_path)
            assert legacy_rows(legacy_engine, backup_metadata) == complete_before
            assert schema_signature(legacy_engine) == schema_before
            assert index_signature(legacy_engine) == indexes_before
            assert "slot_id" not in {column["name"] for column in inspect(legacy_engine).get_columns("exercises")}
        for _ in range(2):
            migrate(legacy_engine)
            assert legacy_rows(legacy_engine, old_metadata) == before
            with legacy_engine.connect() as connection:
                rows = connection.execute(text("SELECT id, slot_id, history_id FROM exercises")).all()
                assert len(rows) == 2
                assert all(identity == slot == history_id for identity, slot, history_id in rows)
                assert connection.execute(text("SELECT weight_step FROM session_exercises")).scalar() is None
                assert connection.execute(text("SELECT recommendation_context_json FROM session_exercises")).scalar() is None
                assert list(connection.execute(text("SELECT version FROM schema_versions ORDER BY version")).scalars()) == list(range(1, 10))
            assert any(item["unique"] and item["column_names"] == ["slot_id"]
                       for item in inspect(legacy_engine).get_indexes("exercises"))
