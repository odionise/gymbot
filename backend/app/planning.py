from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import Exercise, SessionExercise, WorkoutSession, WorkoutTemplate

PHASES = ("light", "medium", "heavy")


def round_to_step(value: float, step: float) -> float:
    unit = Decimal(str(step))
    return float((Decimal(str(value)) / unit).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * unit)


def phase_range(exercise: Exercise, phase: int) -> tuple[int, int]:
    label = PHASES[phase]
    return getattr(exercise, f"{label}_min"), getattr(exercise, f"{label}_max")


def base_weight(exercise: Exercise, phase: int) -> float:
    factor = (float(exercise.light_factor), 1.0, float(exercise.heavy_factor))[phase]
    return round_to_step(float(exercise.medium_weight) * factor, float(exercise.weight_step))


def completed_history(db: Session, exercise_id: str, phase: int) -> list[SessionExercise]:
    return list(db.scalars(
        select(SessionExercise)
        .join(WorkoutSession)
        .where(
            SessionExercise.exercise_id == exercise_id,
            WorkoutSession.phase == phase,
            WorkoutSession.status == "completed",
            SessionExercise.skipped.is_(False),
        )
        .order_by(WorkoutSession.completed_at.desc())
        .limit(2)
    ))


def failed(item: SessionExercise) -> bool:
    return len(item.results) < item.sets_count or any(
        float(result.weight) < float(item.target_weight) or result.reps < item.min_reps
        for result in item.results
    )


def prescription(db: Session, exercise: Exercise, phase: int) -> tuple[float, int, int, int]:
    minimum, maximum = phase_range(exercise, phase)
    previous = completed_history(db, exercise.id, phase)
    if not previous:
        return base_weight(exercise, phase), minimum, minimum, maximum
    last = previous[0]
    weight = float(last.target_weight)
    step = float(exercise.weight_step)
    if len(last.results) == last.sets_count and all(
        float(result.weight) >= weight and result.reps >= maximum for result in last.results
    ):
        return round_to_step(weight + step, step), minimum, minimum, maximum
    if len(previous) == 2 and failed(last) and failed(previous[1]):
        return max(0.0, round_to_step(weight - step, step)), minimum, minimum, maximum
    if failed(last):
        return weight, minimum, minimum, maximum
    next_reps = min(maximum, min(result.reps for result in last.results) + 1)
    return weight, next_reps, minimum, maximum


def get_or_create_session(db: Session, template: WorkoutTemplate, on_date: date) -> WorkoutSession | None:
    open_session = db.scalars(
        select(WorkoutSession)
        .where(WorkoutSession.template_id == template.id, WorkoutSession.status != "completed")
        .order_by(WorkoutSession.scheduled_date)
    ).first()
    if open_session:
        return open_session
    existing = db.scalars(select(WorkoutSession).where(
        WorkoutSession.template_id == template.id,
        WorkoutSession.scheduled_date == on_date,
    )).first()
    if existing:
        return existing
    exercises = [item for item in template.exercises if item.active]
    if not exercises:
        return None
    session = WorkoutSession(
        user_id=template.user_id,
        template_id=template.id,
        template_name=template.name,
        muscle_group=template.muscle_group,
        scheduled_date=on_date,
        phase=template.next_phase,
    )
    db.add(session)
    db.flush()
    for exercise in exercises:
        weight, reps, minimum, maximum = prescription(db, exercise, template.next_phase)
        db.add(SessionExercise(
            session_id=session.id,
            exercise_id=exercise.id,
            name=exercise.name,
            position=exercise.position,
            sets_count=exercise.sets_count,
            target_weight=weight,
            target_reps=reps,
            min_reps=minimum,
            max_reps=maximum,
        ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return db.scalars(select(WorkoutSession).where(
            WorkoutSession.template_id == template.id,
            WorkoutSession.scheduled_date == on_date,
        )).first()
    db.refresh(session)
    return session
