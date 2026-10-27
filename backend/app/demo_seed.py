"""Add repeatable example training history to the local preview user only.

Run inside the local API container: python -m app.demo_seed
The marker IDs make repeated runs a no-op. All inserts share one transaction.
"""

from datetime import datetime, time, timedelta, timezone
import json
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import select

from .config import get_settings
from .db import SessionLocal
from .models import (Exercise, Mesocycle, Movement, SessionExercise, SetResult,
                     TrainingWeek, User, WorkoutSession, WorkoutTemplate)
from .planning import monday


PREFIX = "ДЕМО · "

# Template weekday, title, large interface section, movement definitions.
# Movement: name, main muscle, secondary muscles, anchor, base weight, step,
# number of sets on the first accumulation week.
PROGRAMS = (
    (0, "Верх А", "Грудь, Спина, Плечи", (
        ("Жим штанги лёжа", "Грудь", "Трицепс,Передние дельты", True, 60, 2.5, 6),
        ("Тяга блока к поясу", "Верх спины", "Широчайшие,Бицепс", True, 55, 2.5, 5),
        ("Жим гантелей сидя", "Передние дельты", "Трицепс", False, 18, 2, 4),
    )),
    (3, "Верх Б", "Грудь, Спина, Руки", (
        ("Жим гантелей под углом", "Грудь", "Трицепс,Передние дельты", False, 22, 2, 6),
        ("Тяга верхнего блока", "Широчайшие", "Бицепс,Верх спины", True, 50, 2.5, 5),
        ("Сгибание рук с гантелями", "Бицепс", "Предплечья", False, 12, 2, 4),
        ("Махи гантелями в стороны", "Средние дельты", "", False, 8, 1, 4),
    )),
    (5, "Низ", "Ноги", (
        ("Приседания со штангой", "Квадрицепс", "Ягодичные,Разгибатели спины", True, 80, 2.5, 6),
        ("Жим ногами", "Квадрицепс", "Ягодичные", False, 140, 5, 6),
        ("Румынская тяга", "Бицепс бедра", "Ягодичные,Разгибатели спины", True, 65, 2.5, 5),
        ("Подъёмы на носки", "Икры", "", False, 50, 2.5, 4),
    )),
)


def demo_id(user_id: int, kind: str, *parts: object) -> str:
    return str(uuid5(NAMESPACE_URL, ":".join(("workout-demo-v1", str(user_id), kind, *(str(part) for part in parts)))))


def seed() -> str:
    settings = get_settings()
    if settings.app_env != "development" or settings.dev_telegram_id <= 0:
        raise RuntimeError("Demo history is allowed only for the local development user")
    user_id = settings.dev_telegram_id
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is None:
            raise RuntimeError("Open the local preview first to create its development user")
        marker = demo_id(user_id, "template", PROGRAMS[0][1])
        if db.get(WorkoutTemplate, marker):
            return "Demo history already exists; nothing changed."
        if db.scalar(select(WorkoutTemplate.id).where(
            WorkoutTemplate.user_id == user_id, WorkoutTemplate.name.like(f"{PREFIX}%")
        )):
            raise RuntimeError("Demo-named templates already exist; inspect them before seeding")

        last_week = monday(datetime.now(ZoneInfo(user.timezone)).date()) - timedelta(weeks=1)
        starts = [last_week - timedelta(weeks=7 - index) for index in range(8)]
        existing_weeks = set(db.scalars(select(TrainingWeek.week_start).where(
            TrainingWeek.user_id == user_id, TrainingWeek.week_start.in_(starts)
        )))
        if existing_weeks:
            raise RuntimeError(f"Existing training weeks overlap demo history: {sorted(existing_weeks)}")

        templates = []
        for weekday, title, section, movements in PROGRAMS:
            template = WorkoutTemplate(
                id=demo_id(user_id, "template", title), user_id=user_id,
                name=PREFIX + title, muscle_group=section, weekday=weekday,
                send_time="09:00", active=True,
            )
            db.add(template)
            exercises = []
            for position, (name, main, secondary, anchor, base_weight, step, base_sets) in enumerate(movements):
                movement = Movement(
                    id=demo_id(user_id, "movement", name), user_id=user_id,
                    name=PREFIX + name, primary_group=main, secondary_groups=secondary,
                    is_anchor=anchor, active=True,
                )
                exercise = Exercise(
                    id=demo_id(user_id, "exercise", title, name), template_id=template.id,
                    movement_id=movement.id, name=movement.name, position=position,
                    sets_count=base_sets, medium_weight=base_weight, weight_step=step,
                    rep_min=8, rep_max=12, rir_target=2, active=True,
                )
                db.add_all((movement, exercise))
                exercises.append((exercise, movement, base_weight, step, base_sets))
            templates.append((template, exercises))

        for cycle_index in range(2):
            block_start = starts[cycle_index * 4]
            block = Mesocycle(
                id=demo_id(user_id, "mesocycle", cycle_index), user_id=user_id,
                block_number=cycle_index + 1, start_week=block_start, length_weeks=4,
            )
            db.add(block)
            for within_cycle in range(4):
                index = cycle_index * 4 + within_cycle
                week_start = starts[index]
                deload = within_cycle == 3
                week = TrainingWeek(
                    id=demo_id(user_id, "week", week_start), user_id=user_id,
                    mesocycle_id=block.id, week_start=week_start,
                    week_number=within_cycle + 1,
                    phase_type="deload" if deload else "accumulation",
                    deload_reason="scheduled" if deload else None,
                    feeling_beat_up=index == 6,
                    target_rir=4 if deload else 2,
                    targets_json=json.dumps({"Грудь": [12, 18, 20], "Квадрицепс": [12, 18, 20]}, ensure_ascii=False),
                )
                db.add(week)
                for template, exercises in templates:
                    day = week_start + timedelta(days=template.weekday)
                    completed_at = datetime.combine(day, time(18, 30), timezone.utc)
                    session = WorkoutSession(
                        id=demo_id(user_id, "session", template.id, day),
                        user_id=user_id, template_id=template.id,
                        template_name=template.name, muscle_group=template.muscle_group,
                        scheduled_date=day, actual_date=day, completed_at=completed_at,
                        week_id=week.id, phase_type=week.phase_type,
                        phase=0 if deload else min(within_cycle, 2), status="completed",
                    )
                    db.add(session)
                    for exercise, movement, base_weight, step, base_sets in exercises:
                        sets_count = max(2, base_sets // 2) if deload else base_sets + within_cycle
                        weight = base_weight + cycle_index * step
                        reps = (8 if deload else 8 + within_cycle)
                        rir = 4 if deload else (0.5 if index == 6 and movement.primary_group == "Грудь" else 2)
                        snapshot = SessionExercise(
                            id=demo_id(user_id, "snapshot", session.id, exercise.id),
                            session_id=session.id, exercise_id=exercise.id,
                            movement_id=movement.id, name=movement.name,
                            position=exercise.position, sets_count=sets_count,
                            target_weight=weight, target_reps=reps,
                            min_reps=8, max_reps=12, target_rir=rir,
                            primary_group=movement.primary_group,
                            secondary_groups=movement.secondary_groups,
                            is_anchor=movement.is_anchor, action_label="Демонстрационный план",
                        )
                        db.add(snapshot)
                        for set_index in range(1, sets_count + 1):
                            db.add(SetResult(
                                id=demo_id(user_id, "set", snapshot.id, set_index),
                                session_exercise_id=snapshot.id, set_index=set_index,
                                weight=weight, reps=reps, rir_reported=rir,
                                rir_target=rir, is_working=True,
                            ))
        db.commit()
        return (f"Added {len(templates)} demo programs and {len(starts) * len(templates)} "
                f"completed workouts from {starts[0]} through {starts[-1] + timedelta(days=5)}.")


if __name__ == "__main__":
    print(seed())
