"""The existing synthetic preview seed respects assignment/snapshot identities."""

from types import SimpleNamespace

from sqlalchemy import func, select

from app import demo_seed, main
from app.db import Base
from app.models import Exercise, SessionExercise, User, WorkoutSession


def test_demo_seed_has_stable_identities_frozen_steps_and_is_repeatable(database, monkeypatch):
    monkeypatch.setattr(demo_seed, "get_settings", lambda: SimpleNamespace(
        app_env="development", dev_telegram_id=1001,
    ))
    monkeypatch.setattr(demo_seed, "SessionLocal", database)
    monkeypatch.setattr(demo_seed, "datetime", main.datetime)
    with database() as db:
        db.add(User(telegram_id=1001))
        db.commit()

    assert demo_seed.seed().startswith("Added 3 demo programs and 24 completed workouts")
    with database() as db:
        assert db.scalar(select(func.count()).select_from(WorkoutSession)) == 24
        assignments = list(db.scalars(select(Exercise)))
        snapshots = list(db.scalars(select(SessionExercise)))
        assert len(assignments) == 11
        assert len(snapshots) == 88
        assert all(item.id == item.slot_id == item.history_id for item in assignments)
        steps = {item.id: item.weight_step for item in assignments}
        assert all(item.weight_step == steps[item.exercise_id] for item in snapshots)

        # A later manual program edit must neither reseed data nor rewrite the
        # equipment step recorded in already completed synthetic workouts.
        assignments[0].weight_step = 9
        assignments[0].medium_weight = 1
        db.commit()

        def all_rows():
            return {table.name: sorted((tuple(row) for row in db.execute(select(table))), key=repr)
                    for table in Base.metadata.sorted_tables}

        before = all_rows()
        assert demo_seed.seed() == "Demo history already exists; nothing changed."
        db.expire_all()
        assert all_rows() == before
        assert all(item.weight_step == steps[item.exercise_id] for item in db.scalars(select(SessionExercise)))
