from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.analytics import progress_for_user
from app.bot import format_plan
from app.db import make_engine
from app.main import change_sets_count, complete_session, create_exercise, create_movement, create_template, manual_deload, reschedule, save_set, update_muscle_target, update_recovery
from app.migrations import migrate
from app.models import Exercise, Movement, SessionExercise, SetResult, TrainingWeek, User, WorkoutSession, WorkoutTemplate, utcnow
from app.planning import get_or_create_session, next_set_suggestion
from app.schemas import ExerciseIn, MovementIn, MuscleTargetIn, RecoveryIn, RescheduleIn, ResultIn, SetsCountIn, TemplateIn


@pytest.fixture
def database(tmp_path):
    engine = make_engine('sqlite:///' + str(tmp_path / 'test.db'))
    migrate(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


def make_program(db: Session, user_id=1, sets=3, secondary=''):
    db.add(User(telegram_id=user_id))
    template = WorkoutTemplate(user_id=user_id, name='Верх', muscle_group='Грудь, Руки',
                               weekday=0, send_time='09:00')
    db.add(template)
    db.flush()
    movement = Movement(user_id=user_id, name='Жим', primary_group='Грудь',
                        secondary_groups=secondary, is_anchor=True)
    db.add(movement)
    db.flush()
    exercise = Exercise(template_id=template.id, movement_id=movement.id, name='Жим',
                        position=0, sets_count=sets, medium_weight=80, weight_step=2.5,
                        rep_min=6, rep_max=12, rir_target=2)
    db.add(exercise)
    db.commit()
    return template, exercise


def finish(db, session, reps=8, rir=2, actual=None):
    item = session.exercises[0]
    for index in range(1, item.sets_count + 1):
        db.add(SetResult(session_exercise_id=item.id, set_index=index,
                         weight=item.target_weight, reps=reps, rir_reported=rir,
                         rir_target=item.target_rir, is_working=True))
    session.status = 'completed'
    session.actual_date = actual or session.scheduled_date
    session.completed_at = utcnow()
    db.commit()


def test_double_progression_and_deload_reentry(database):
    with database() as db:
        template, _ = make_program(db)
        start = date(2026, 10, 26)
        first = get_or_create_session(db, template, start)
        assert first.phase_type == 'accumulation'
        assert float(first.exercises[0].target_weight) == 80
        assert 'ПДО 2' in format_plan(first, start)
        finish(db, first, reps=12, rir=2)
        second = get_or_create_session(db, template, start + timedelta(weeks=1))
        assert float(second.exercises[0].target_weight) == 82.5
        assert second.exercises[0].target_reps == 6
        assert second.exercises[0].sets_count == 4
        finish(db, second, reps=8, rir=2)
        third = get_or_create_session(db, template, start + timedelta(weeks=2))
        assert third.exercises[0].sets_count == 5
        finish(db, third, reps=8, rir=1.5)
        fourth = get_or_create_session(db, template, start + timedelta(weeks=3))
        assert fourth.phase_type == 'deload'
        assert fourth.exercises[0].sets_count < template.exercises[0].sets_count
        assert float(fourth.exercises[0].target_rir) == 4
        finish(db, fourth, reps=8, rir=4)
        fifth = get_or_create_session(db, template, start + timedelta(weeks=4))
        assert fifth.phase_type == 'accumulation'
        assert 'Возвращение' in fifth.exercises[0].action_label


def test_fractional_hard_sets_and_suggestion(database):
    with database() as db:
        template, _ = make_program(db, sets=2, secondary='Трицепс')
        first = get_or_create_session(db, template, date(2026, 10, 26))
        item = first.exercises[0]
        db.add(SetResult(session_exercise_id=item.id, set_index=1, weight=80,
                         reps=8, rir_reported=4, rir_target=2, is_working=True))
        db.commit()
        suggestion = next_set_suggestion(item, 2.5)
        assert suggestion['weight'] == 85
        db.add(SetResult(session_exercise_id=item.id, set_index=2, weight=80,
                         reps=8, rir_reported=2, rir_target=2, is_working=True))
        first.status, first.actual_date, first.completed_at = 'completed', first.scheduled_date, utcnow()
        db.commit()
        db.expire_all()
        progress = progress_for_user(db, 1)
        chest = next(row for row in progress['weeks'] if row['group'] == 'Грудь')
        triceps = next(row for row in progress['weeks'] if row['group'] == 'Трицепс')
        assert chest['hard_sets'] == 1
        assert triceps['hard_sets'] == 0.5


def test_route_validation_and_owner(database):
    with database() as db:
        one, two = User(telegram_id=101), User(telegram_id=202)
        db.add_all([one, two])
        db.commit()
        template = create_template(TemplateIn(name='Верх', muscle_group='Грудь', weekday=0, send_time='09:00'), one, db)
        with pytest.raises(HTTPException) as missing_muscle:
            create_exercise(template['id'], ExerciseIn(name='Без группы', medium_weight=60), one, db)
        assert missing_muscle.value.status_code == 422
        movement = create_movement(MovementIn(name='Жим', primary_group='Грудь',
            secondary_groups=['Трицепс'], is_anchor=True), one, db)
        exercise = create_exercise(template['id'], ExerciseIn(name='Жим', movement_id=movement['id'],
            sets_count=1, medium_weight=60, rep_min=6, rep_max=12), one, db)
        assert exercise['movement_id'] == movement['id']
        session = get_or_create_session(db, db.get(WorkoutTemplate, template['id']), date(2026, 10, 26))
        item = session.exercises[0]
        with pytest.raises(HTTPException) as denied:
            save_set(item.id, 1, ResultIn(weight=60, reps=8, rir_reported=2), two, db)
        assert denied.value.status_code == 404
        saved = save_set(item.id, 1, ResultIn(weight=60, reps=8, rir_reported=2), one, db)
        assert saved['exercises'][0]['results'][0]['rir_reported'] == 2
        assert complete_session(session.id, one, db)['status'] == 'completed'
        assert progress_for_user(db, 101)['weeks']


def test_migration_is_idempotent(database):
    with database() as db:
        make_program(db)
        migrate(db.bind)
        assert db.get(User, 1).volume_cap == 20


def test_week_postponement_and_auto_deload(database):
    with database() as db:
        template, _ = make_program(db)
        start = date(2026, 10, 26)
        for offset in range(3):
            session = get_or_create_session(db, template, start + timedelta(weeks=offset))
            finish(db, session, rir=2)
        postponed = get_or_create_session(db, template, start + timedelta(weeks=3))
        assert postponed.phase_type == 'accumulation'
        assert db.get(TrainingWeek, postponed.week_id).is_postponed
        finish(db, postponed, rir=2)
        deload = get_or_create_session(db, template, start + timedelta(weeks=4))
        assert deload.phase_type == 'deload'

    with database() as db:
        deload = db.query(TrainingWeek).filter_by(phase_type='deload').first()
        assert deload.deload_reason == 'scheduled'


def test_migration_preserves_unknown_rir(tmp_path):
    engine = make_engine('sqlite:///' + str(tmp_path / 'legacy.db'))
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE users (telegram_id BIGINT PRIMARY KEY, chat_id BIGINT, timezone VARCHAR(64), created_at DATETIME)'))
        connection.execute(text('CREATE TABLE set_results (id VARCHAR(36) PRIMARY KEY, session_exercise_id VARCHAR(36), set_index INTEGER, weight NUMERIC, reps INTEGER)'))
        connection.execute(text("INSERT INTO users (telegram_id, timezone) VALUES (9, 'Europe/Moscow')"))
        connection.execute(text("INSERT INTO set_results (id, session_exercise_id, set_index, weight, reps) VALUES ('old', 'slot', 1, 50, 10)"))
    migrate(engine)
    migrate(engine)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT rir_reported FROM set_results WHERE id='old'")).scalar() is None
        assert connection.execute(text('SELECT volume_cap FROM users WHERE telegram_id=9')).scalar() == 20
    engine.dispose()


def test_manual_deload_and_reschedule(database):
    with database() as db:
        template, _ = make_program(db)
        user = db.get(User, 1)
        start = date(2026, 10, 26)
        manual = manual_deload(start, user, db)
        assert manual['phase_type'] == 'deload'
        session = get_or_create_session(db, template, start)
        assert session.phase_type == 'deload'
        moved = reschedule(session.id, RescheduleIn(scheduled_date='2026-11-02'), user, db)
        assert moved['scheduled_date'] == '2026-11-02'
        assert moved['phase_type'] == 'accumulation'


def test_missed_deload_is_repeated(database):
    with database() as db:
        template, _ = make_program(db, sets=4)
        user = db.get(User, 1)
        start = date(2026, 10, 26)
        for offset in range(3):
            session = get_or_create_session(db, template, start + timedelta(weeks=offset))
            finish(db, session, rir=1.5)
        deload = get_or_create_session(db, template, start + timedelta(weeks=3))
        assert deload.phase_type == 'deload'
        change_sets_count(deload.exercises[0].id, SetsCountIn(sets_count=6), user, db)
        db.expire_all()
        deload = db.get(type(deload), deload.id)
        finish(db, deload, rir=4)
        next_session = get_or_create_session(db, template, start + timedelta(weeks=4))
        assert db.get(TrainingWeek, deload.week_id).missed_deload
        assert next_session.phase_type == 'deload'
        assert any(row['phase'] == 'missed_deload' for row in progress_for_user(db, 1)['weeks'])


def test_early_deload_and_target_snapshot(database):
    with database() as db:
        template, _ = make_program(db)
        user = db.get(User, 1)
        update_muscle_target('Грудь', MuscleTargetIn(min_sets=10, max_sets=14, cap_sets=16), user, db)
        first = get_or_create_session(db, template, date(2026, 10, 26))
        assert 'Грудь' in db.get(TrainingWeek, first.week_id).targets_json
        finish(db, first, rir=0.5)
        second = get_or_create_session(db, template, date(2026, 11, 2))
        assert second.phase_type == 'deload'
        assert db.get(TrainingWeek, second.week_id).deload_reason == 'auto'


def test_warmup_does_not_count(database):
    assert ResultIn(weight=40, reps=10, is_working=False).rir_reported is None
    with pytest.raises(ValueError):
        ResultIn(weight=80, reps=8)
    with database() as db:
        template, _ = make_program(db, sets=1)
        first = get_or_create_session(db, template, date(2026, 10, 26))
        item = first.exercises[0]
        db.add(SetResult(session_exercise_id=item.id, set_index=-1, weight=40, reps=10,
                         rir_reported=None, is_working=False))
        finish(db, first, rir=2)
        db.expire_all()
        row = progress_for_user(db, 1)['weeks'][0]
        assert row['hard_sets'] == 1
        assert row['working_sets'] == 1


def test_recovery_flag_prevents_postponement(database):
    with database() as db:
        template, _ = make_program(db)
        user = db.get(User, 1)
        start = date(2026, 10, 26)
        for offset in range(3):
            session = get_or_create_session(db, template, start + timedelta(weeks=offset))
            finish(db, session, rir=2)
        update_recovery(start + timedelta(weeks=2), RecoveryIn(feeling_beat_up=True), user, db)
        fourth = get_or_create_session(db, template, start + timedelta(weeks=3))
        assert fourth.phase_type == 'deload'
        assert db.get(TrainingWeek, fourth.week_id).deload_reason == 'scheduled'


def test_legacy_session_remains_visible_without_hard_sets(database):
    with database() as db:
        template, exercise = make_program(db)
        legacy = WorkoutSession(user_id=1, template_id=template.id, template_name=template.name,
                                muscle_group='Грудь', scheduled_date=date(2026, 10, 19),
                                phase=1, status='completed', completed_at=utcnow())
        db.add(legacy)
        db.flush()
        slot = SessionExercise(session_id=legacy.id, exercise_id=exercise.id, name='Жим',
                               position=0, sets_count=1, target_weight=80, target_reps=8,
                               min_reps=8, max_reps=12)
        db.add(slot)
        db.flush()
        db.add(SetResult(session_exercise_id=slot.id, set_index=1, weight=80, reps=8))
        db.commit()
        progress = progress_for_user(db, 1)
        assert len(progress['exercises'][0]['points']) == 1
        assert progress['weeks'] == []
