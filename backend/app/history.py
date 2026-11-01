"""Assignment identities and comparable history, shared by planning and analytics."""

from collections import defaultdict
from datetime import timezone

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from .models import Exercise, Movement, SessionExercise, WorkoutSession, WorkoutTemplate


def slot_id(exercise: Exercise) -> str:
    return exercise.slot_id or exercise.id


def history_id(exercise: Exercise) -> str:
    return exercise.history_id or exercise.id


def snapshot_key(item: SessionExercise) -> tuple[str, str, str | None, str]:
    return slot_id(item.exercise), history_id(item.exercise), item.movement_id, item.kind


def movement_is_used(db: Session, movement_id: str) -> bool:
    return bool(db.scalar(select(or_(
        exists().where(Exercise.movement_id == movement_id),
        exists().where(SessionExercise.movement_id == movement_id),
    ))))


def comparable_history(db: Session, exercise: Exercise):
    template = db.get(WorkoutTemplate, exercise.template_id)
    movement = db.get(Movement, exercise.movement_id) if exercise.movement_id else None
    if not template or not movement:
        return select(SessionExercise).where(False)
    # A shared base alone is insufficient for legacy assignments that were
    # mutated in place. The recorded movement and kind must also match.
    return select(SessionExercise).join(
        WorkoutSession, SessionExercise.session_id == WorkoutSession.id,
    ).join(Exercise, SessionExercise.exercise_id == Exercise.id).where(
        WorkoutSession.user_id == template.user_id,
        WorkoutSession.template_id == template.id,
        Exercise.template_id == exercise.template_id,
        func.coalesce(Exercise.slot_id, Exercise.id) == slot_id(exercise),
        func.coalesce(Exercise.history_id, Exercise.id) == history_id(exercise),
        SessionExercise.movement_id == movement.id,
        SessionExercise.kind == movement.kind,
    )


def history_options(db: Session, exercise: Exercise, movement: Movement) -> dict:
    template = db.get(WorkoutTemplate, exercise.template_id)
    rows = list(db.scalars(select(SessionExercise).join(
        WorkoutSession, SessionExercise.session_id == WorkoutSession.id,
    ).join(Exercise, SessionExercise.exercise_id == Exercise.id).where(
        WorkoutSession.user_id == template.user_id,
        WorkoutSession.template_id == template.id,
        Exercise.template_id == template.id,
        func.coalesce(Exercise.slot_id, Exercise.id) == slot_id(exercise),
    )))
    by_base = defaultdict(list)
    for row in rows:
        by_base[history_id(row.exercise)].append(row)
    options = []
    excluded = False
    for base, records in by_base.items():
        identities = {(row.movement_id, row.kind) for row in records}
        if any(value[0] is None for value in identities) or len(identities) != 1:
            excluded = True
            continue
        if identities != {(movement.id, movement.kind)}:
            continue
        completed = [row for row in records if row.session.status == "completed" and not row.skipped
                     and (any(result.is_working for result in row.results) if row.kind == "strength"
                          else row.actual_duration_minutes is not None)]
        if not completed:
            continue
        completed.sort(key=lambda row: (
            row.session.completed_at.replace(tzinfo=timezone.utc).timestamp()
            if row.session.completed_at else float("-inf"), row.session.id,
        ))
        last = completed[-1]
        working = [result for result in last.results if result.is_working]
        result = working[0] if working else None
        day = last.session.actual_date or last.session.scheduled_date
        options.append({
            "history_id": base, "name": last.name, "kind": last.kind,
            "completed_sessions": len({row.session_id for row in completed}),
            "last_completed_date": day.isoformat(),
            "last_result": {"weight": float(result.weight) if result else None,
                            "reps": result.reps if result else None,
                            "duration_minutes": last.actual_duration_minutes},
        })
    options.sort(key=lambda option: (option["last_completed_date"], option["history_id"]), reverse=True)
    return {"movement_id": movement.id, "options": options, "excluded_legacy": excluded}
