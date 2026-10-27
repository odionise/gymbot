"""Small, additive migrations for databases created before the progression engine.

The schema version is stored in the database. Existing workout rows are never
rewritten: in particular their unknown RIR must stay NULL.
"""

from sqlalchemy import inspect, text

from .db import Base


ADDITIONS = {
    "users": {"volume_cap": "INTEGER NOT NULL DEFAULT 20"},
    "exercises": {
        "movement_id": "VARCHAR(36)", "rep_min": "INTEGER", "rep_max": "INTEGER",
        "rir_target": "NUMERIC(3, 1)",
    },
    "workout_sessions": {
        "actual_date": "DATE", "week_id": "VARCHAR(36)", "phase_type": "VARCHAR(16)",
    },
    "session_exercises": {
        "movement_id": "VARCHAR(36)", "primary_group": "VARCHAR(80)",
        "secondary_groups": "VARCHAR(240)", "target_rir": "NUMERIC(3, 1)",
        "action_label": "VARCHAR(180)", "is_anchor": "BOOLEAN NOT NULL DEFAULT FALSE",
    },
    "set_results": {
        "rir_reported": "NUMERIC(3, 1)", "rir_target": "NUMERIC(3, 1)",
        "is_working": "BOOLEAN NOT NULL DEFAULT TRUE",
    },
}


def migrate(engine):
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE IF NOT EXISTS schema_versions (version INTEGER PRIMARY KEY)"))
        version = connection.execute(text("SELECT MAX(version) FROM schema_versions")).scalar() or 0
        inspector = inspect(connection)
        if version < 1:
            for table, additions in ADDITIONS.items():
                existing = {column["name"] for column in inspector.get_columns(table)}
                for name, specification in additions.items():
                    if name not in existing:
                        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {specification}"))
            connection.execute(text("INSERT INTO schema_versions (version) VALUES (1)"))
        if version < 2:
            existing = {column["name"] for column in inspector.get_columns("training_weeks")}
            if "targets_json" not in existing:
                connection.execute(text("ALTER TABLE training_weeks ADD COLUMN targets_json VARCHAR(4000) NOT NULL DEFAULT '{}'"))
            connection.execute(text("INSERT INTO schema_versions (version) VALUES (2)"))
        if version < 3:
            existing = {column["name"] for column in inspector.get_columns("training_weeks")}
            if "feeling_beat_up" not in existing:
                connection.execute(text("ALTER TABLE training_weeks ADD COLUMN feeling_beat_up BOOLEAN NOT NULL DEFAULT FALSE"))
            connection.execute(text("INSERT INTO schema_versions (version) VALUES (3)"))
        if version < 4:
            additions = {
                "movements": {"kind": "VARCHAR(16) NOT NULL DEFAULT 'strength'"},
                "exercises": {"duration_minutes": "INTEGER"},
                "session_exercises": {
                    "kind": "VARCHAR(16) NOT NULL DEFAULT 'strength'",
                    "target_duration_minutes": "INTEGER",
                    "actual_duration_minutes": "INTEGER",
                },
            }
            for table, columns in additions.items():
                existing = {column["name"] for column in inspector.get_columns(table)}
                for name, specification in columns.items():
                    if name not in existing:
                        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {specification}"))
            connection.execute(text("INSERT INTO schema_versions (version) VALUES (4)"))
