"""Migration 5 → 6 and rollback through a verified synthetic backup."""

from sqlalchemy import MetaData, inspect, text
from sqlalchemy.orm import Session

from app.main import session_detail
from app.migrations import migrate
from app.models import Exercise, SessionExercise, User
from app.planning import get_or_create_session
from test_history import START, finish, program
from test_migrations_legacy import (index_signature, legacy_engine, legacy_rows,
                                    restore_sql_backup, save_sql_backup, schema_signature)


def test_version_five_upgrade_and_backup_restore_preserve_facts_and_unknown_context(legacy_engine, tmp_path):
    migrate(legacy_engine)
    with Session(legacy_engine, expire_on_commit=False) as db:
        user, template, exercise_id = program(db)
        db.get(Exercise, exercise_id).rir_target = 0
        session = get_or_create_session(db, template, START)
        session_id, item_id = session.id, session.exercises[0].id
        finish(db, user, session)
        item = db.get(SessionExercise, item_id)
        item.weight_step = None
        item.results[0].rir_reported = None
        item.results[1].rir_reported = 0
        db.commit()

    # Remove exactly the stage 2 addition, retaining every v5 column, table,
    # index and stored value. This is the complete previous schema shape.
    with legacy_engine.begin() as connection:
        connection.execute(text("ALTER TABLE session_exercises DROP COLUMN recommendation_context_json"))
        connection.execute(text("DELETE FROM schema_versions WHERE version >= 6"))
    metadata = MetaData()
    metadata.reflect(legacy_engine)
    complete_before = legacy_rows(legacy_engine, metadata)
    schema_before, indexes_before = schema_signature(legacy_engine), index_signature(legacy_engine)
    old_data = MetaData()
    for table in metadata.sorted_tables:
        if table.name != "schema_versions":
            table.to_metadata(old_data)
    facts_before = legacy_rows(legacy_engine, old_data)
    backup = tmp_path / "synthetic-v5-backup.sql.json"
    save_sql_backup(legacy_engine, metadata, backup)

    for phase in ("upgrade", "restored-upgrade"):
        if phase == "restored-upgrade":
            restore_sql_backup(legacy_engine, backup)
            assert legacy_rows(legacy_engine, metadata) == complete_before
            assert schema_signature(legacy_engine) == schema_before
            assert index_signature(legacy_engine) == indexes_before
            assert "recommendation_context_json" not in {
                column["name"] for column in inspect(legacy_engine).get_columns("session_exercises")
            }
        for _ in range(2):
            migrate(legacy_engine)
            assert legacy_rows(legacy_engine, old_data) == facts_before
            with legacy_engine.connect() as connection:
                assert list(connection.execute(text("SELECT version FROM schema_versions ORDER BY version")).scalars()) == [1, 2, 3, 4, 5, 6, 7, 8]
                assert connection.execute(text("SELECT recommendation_context_json FROM session_exercises")).scalar() is None
                assert connection.execute(text("SELECT weight_step FROM session_exercises")).scalar() is None
                assert connection.execute(text("SELECT rir_target FROM exercises")).scalar() == 0
            column = next(column for column in inspect(legacy_engine).get_columns("session_exercises")
                          if column["name"] == "recommendation_context_json")
            assert column["nullable"] is True
            with Session(legacy_engine) as db:
                response = session_detail(session_id, db.get(User, 1001), db)
                row = response["exercises"][0]
                assert row["recommendation"] is None
                assert [result["rir_reported"] for result in row["results"]] == [None, 0]
        # A subsequent restart must preserve newly captured context as well as
        # unknown old values; migrations are not a source of recommendations.
        marker = '{"version":1,"calculated":null,"manual_override":{"weight":0}}'
        with legacy_engine.begin() as connection:
            connection.execute(text("UPDATE session_exercises SET recommendation_context_json = :context WHERE id = :id"),
                               {"context": marker, "id": item_id})
        migrate(legacy_engine)
        with legacy_engine.connect() as connection:
            assert connection.execute(text("SELECT recommendation_context_json FROM session_exercises WHERE id = :id"),
                                      {"id": item_id}).scalar() == marker
        assert legacy_rows(legacy_engine, old_data) == facts_before
