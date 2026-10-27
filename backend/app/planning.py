from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import json
from statistics import mean, median

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import Exercise, Mesocycle, Movement, MuscleTarget, SessionExercise, TrainingWeek, User, WorkoutSession, WorkoutTemplate
from .muscles import split_details

PHASES = ("light", "medium", "heavy")  # historical labels


def round_to_step(value: float, step: float) -> float:
    unit = Decimal(str(step))
    return float((Decimal(str(max(0, value))) / unit).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * unit)


def monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def movement_for(db: Session, exercise: Exercise, user_id: int) -> Movement:
    if exercise.movement_id:
        found = db.get(Movement, exercise.movement_id)
        if found:
            return found
    # Legacy plans cannot be classified anatomically from a workout name.
    movement = Movement(user_id=user_id, name=exercise.name, primary_group="Не назначено")
    db.add(movement)
    db.flush()
    exercise.movement_id = movement.id
    exercise.rep_min = exercise.rep_min or exercise.medium_min
    exercise.rep_max = exercise.rep_max or exercise.medium_max
    exercise.rir_target = exercise.rir_target or 2
    return movement


def completed_new(db: Session, user_id: int) -> list[WorkoutSession]:
    return list(db.scalars(select(WorkoutSession).where(
        WorkoutSession.user_id == user_id, WorkoutSession.status == "completed",
        WorkoutSession.phase_type.is_not(None),
    ).order_by(WorkoutSession.completed_at)))


def week_stats(db: Session, user_id: int, start: date) -> dict:
    sessions = [s for s in completed_new(db, user_id) if s.actual_date and monday(s.actual_date) == start]
    hard, working = defaultdict(float), defaultdict(float)
    rir = []
    for session in sessions:
        for exercise in session.exercises:
            if exercise.skipped or not exercise.primary_group or exercise.primary_group == "Не назначено":
                continue
            groups = [(exercise.primary_group, 1.0)] + [(g, 0.5) for g in split_details(exercise.secondary_groups)]
            for result in exercise.results:
                if not result.is_working:
                    continue
                for group, factor in groups:
                    working[group] += factor
                    if result.rir_reported is not None and float(result.rir_reported) <= 3:
                        hard[group] += factor
                if result.rir_reported is not None:
                    rir.append(float(result.rir_reported))
    return {"hard": dict(hard), "working": dict(working),
            "avg_rir": mean(rir) if rir else None, "sessions": sessions}


def declining_anchor(db: Session, user_id: int) -> bool:
    by_slot = defaultdict(list)
    for session in completed_new(db, user_id):
        if session.phase_type != "accumulation":
            continue
        for item in session.exercises:
            sets = [r for r in item.results if r.is_working and r.rir_reported is not None]
            if item.is_anchor and sets:
                by_slot[item.exercise_id].append((float(sets[0].weight), mean(r.reps for r in sets)))
    return any(len(rows) >= 4 and len({weight for weight, _ in rows[-4:]}) == 1
               and all(rows[-i][1] < rows[-i-1][1] for i in (1, 2, 3))
               for rows in by_slot.values())


def mark_missed_deload(db: Session, week: TrainingWeek | None) -> None:
    if not week or week.phase_type != "deload":
        return
    actual = sum(week_stats(db, week.user_id, week.week_start)["working"].values())
    earlier = list(db.scalars(select(TrainingWeek).where(
        TrainingWeek.user_id == week.user_id, TrainingWeek.week_start < week.week_start,
        TrainingWeek.phase_type == "accumulation",
    ).order_by(TrainingWeek.week_start.desc()).limit(2)))
    baselines = [sum(week_stats(db, week.user_id, item.week_start)["working"].values()) for item in earlier]
    week.missed_deload = bool(baselines and median(baselines) > 0 and actual >= 0.8 * median(baselines))


def resolve_week(db: Session, user_id: int, on_date: date) -> TrainingWeek:
    start = monday(on_date)
    existing = db.scalar(select(TrainingWeek).where(
        TrainingWeek.user_id == user_id, TrainingWeek.week_start == start))
    if existing:
        return existing
    prior = db.scalar(select(TrainingWeek).where(
        TrainingWeek.user_id == user_id, TrainingWeek.week_start < start
    ).order_by(TrainingWeek.week_start.desc()))
    mark_missed_deload(db, prior)
    last_stats = week_stats(db, user_id, start - timedelta(days=7))
    avg_rir = last_stats["avg_rir"]
    decline = declining_anchor(db, user_id)
    fatigue = (avg_rir is not None and avg_rir < 1) or decline
    if prior is None or (prior.phase_type == "deload" and not prior.missed_deload) or (start - prior.week_start).days > 35:
        number = 1
        block = db.get(Mesocycle, prior.mesocycle_id).block_number + 1 if prior else 1
        mesocycle = Mesocycle(user_id=user_id, block_number=block, start_week=start)
        db.add(mesocycle)
        db.flush()
    else:
        mesocycle = db.get(Mesocycle, prior.mesocycle_id)
        number = 1 + (start - mesocycle.start_week).days // 7
        if number > 5 or (number == 5 and not prior.is_postponed and not prior.missed_deload):
            mesocycle = Mesocycle(user_id=user_id, block_number=mesocycle.block_number + 1, start_week=start)
            db.add(mesocycle)
            db.flush()
            number = 1
    scheduled = number >= 4
    postpone = (scheduled and number == 4 and not fatigue and avg_rir is not None
                and avg_rir >= 2 and not (prior and prior.feeling_beat_up))
    phase = "deload" if fatigue or (scheduled and not postpone) else "accumulation"
    reason = "auto" if fatigue else "scheduled" if phase == "deload" else None
    saved_targets = {item.muscle_group: item for item in db.scalars(select(MuscleTarget).where(
        MuscleTarget.user_id == user_id))}
    targets = {group: [item.min_sets, item.max_sets, item.cap_sets]
               for group, item in saved_targets.items()}
    week = TrainingWeek(user_id=user_id, mesocycle_id=mesocycle.id,
                        week_start=start, week_number=number, phase_type=phase,
                        deload_reason=reason, is_postponed=postpone,
                        target_rir=4 if phase == "deload" else 2,
                        targets_json=json.dumps(targets, ensure_ascii=False))
    db.add(week)
    db.flush()
    return week


def latest_accumulation(db: Session, exercise_id: str) -> list[SessionExercise]:
    return list(db.scalars(select(SessionExercise).join(WorkoutSession).where(
        SessionExercise.exercise_id == exercise_id,
        WorkoutSession.status == "completed",
        WorkoutSession.phase_type == "accumulation",
        SessionExercise.skipped.is_(False),
    ).order_by(WorkoutSession.completed_at.desc()).limit(3)))


def prescription(db: Session, exercise: Exercise, week: TrainingWeek, reentry: bool) -> tuple[float, int, str]:
    minimum = exercise.rep_min or exercise.medium_min
    maximum = exercise.rep_max or exercise.medium_max
    step = float(exercise.weight_step)
    history = latest_accumulation(db, exercise.id)
    if not history:
        return round_to_step(float(exercise.medium_weight), step), minimum, "Стартовый вес"
    weights = [float(next((r.weight for r in item.results if r.is_working), item.target_weight))
               for item in history]
    weight = round_to_step(median(weights), step)
    last = history[0]
    results = [r for r in last.results if r.is_working]
    if week.phase_type == "deload":
        return weight, minimum, "Легкая неделя: вес без повышения"
    if reentry:
        return weight, minimum, "Возвращение после легкой недели: вес без повышения"
    if results and len(results) == last.sets_count and all(
        r.reps >= maximum and r.rir_reported is not None and float(r.rir_reported) >= 1 for r in results
    ):
        return round_to_step(weight + step, step), minimum, "Верх диапазона: +1 шаг веса"
    if results and all(r.rir_reported is not None and float(r.rir_reported) >= 1 for r in results):
        return weight, min(maximum, round(median(r.reps for r in results)) + 1), "Добавить повторение"
    return weight, minimum, "Сохранить вес: проверить восстановление"


def planned_counts(db: Session, user_id: int, week: TrainingWeek) -> dict[str, int]:
    templates = list(db.scalars(select(WorkoutTemplate).where(
        WorkoutTemplate.user_id == user_id, WorkoutTemplate.active.is_(True))))
    exercises = [e for t in templates for e in t.exercises if e.active]
    counts = {e.id: e.sets_count for e in exercises}
    movements = {e.id: movement_for(db, e, user_id) for e in exercises}
    def volume(group: str) -> float:
        return sum(counts[e.id] * (1 if movements[e.id].primary_group == group else
                   0.5 if group in split_details(movements[e.id].secondary_groups) else 0)
                   for e in exercises)
    groups = ({m.primary_group for m in movements.values() if m.primary_group != "Не назначено"}
              | {group for m in movements.values() for group in split_details(m.secondary_groups)})
    targets = json.loads(week.targets_json or "{}")
    default_cap = db.get(User, user_id).volume_cap
    def enforce_limits(deload: bool = False) -> dict[str, int]:
        for group in sorted(groups):
            limit = 8 if deload else targets.get(group, [12, 18, default_cap])[2]
            candidates = sorted((e for e in exercises if movements[e.id].primary_group == group
                                 or group in split_details(movements[e.id].secondary_groups)),
                                key=lambda e: (movements[e.id].is_anchor, -counts[e.id], e.id))
            while volume(group) > limit and any(counts[e.id] > 1 for e in candidates):
                candidate = next(e for e in candidates if counts[e.id] > 1)
                counts[candidate.id] -= 1
        return counts
    if week.phase_type == "deload":
        counts = {e.id: max(1, round(e.sets_count * 0.5)) for e in exercises}
        return enforce_limits(deload=True)
    prior = db.scalar(select(TrainingWeek).where(
        TrainingWeek.user_id == user_id, TrainingWeek.week_start < week.week_start
    ).order_by(TrainingWeek.week_start.desc()))
    if prior and prior.phase_type == "deload" and not prior.missed_deload:
        counts = {e.id: min(e.sets_count, max(1, round(e.sets_count * 0.5) + 1)) for e in exercises}
        return enforce_limits()
    if week.week_number < 2 or not prior:
        return enforce_limits()
    before_prior = db.scalar(select(TrainingWeek).where(
        TrainingWeek.user_id == user_id, TrainingWeek.week_start < prior.week_start
    ).order_by(TrainingWeek.week_start.desc()))
    if week.week_number == 2 and before_prior and before_prior.phase_type == "deload" and not before_prior.missed_deload:
        return enforce_limits()
    if prior.feeling_beat_up:
        if before_prior and before_prior.feeling_beat_up:
            counts = {e.id: max(1, round(e.sets_count * 0.75)) for e in exercises}
        return enforce_limits()
    stats = week_stats(db, user_id, prior.week_start)
    completed_templates = {s.template_id for s in stats["sessions"]}
    if (stats["avg_rir"] is None or stats["avg_rir"] < 1 or declining_anchor(db, user_id)
            or any(t.id not in completed_templates for t in templates)):
        return enforce_limits()
    for session in stats["sessions"]:
        for item in session.exercises:
            if item.exercise_id in counts and not item.skipped:
                counts[item.exercise_id] = item.sets_count
    by_group = defaultdict(list)
    for e in exercises:
        movement = movements[e.id]
        if movement.primary_group != "Не назначено":
            by_group[movement.primary_group].append((e, movement))
    for group, options in by_group.items():
        cap = targets.get(group, [12, 18, default_cap])[2]
        options.sort(key=lambda pair: (not pair[1].is_anchor, pair[0].position, pair[0].id))
        if volume(group) < cap:
            candidate = options[(week.week_number - 2) % len(options)][0]
            counts[candidate.id] = min(12, counts[candidate.id] + 1)
    return enforce_limits()


def next_set_suggestion(item: SessionExercise, step: float) -> dict | None:
    results = sorted((r for r in item.results if r.is_working), key=lambda r: r.set_index)
    if not results or len(results) >= item.sets_count:
        return None
    last = results[-1]
    if last.rir_reported is None or item.target_rir is None:
        return None
    difference = float(last.rir_reported) - float(item.target_rir)
    weight = float(last.weight)
    if difference >= 2 and item.session.phase_type != "deload":
        weight += 2 * step
        reason = "ПДО выше цели: увеличить вес"
    elif difference <= -2:
        weight = max(0, weight - 2 * step)
        reason = "ПДО ниже цели: снизить вес"
    else:
        reason = "Вес в целевом коридоре"
    reps = max(item.min_reps, min(item.max_reps, last.reps - 1 if difference <= -1 else item.target_reps))
    return {"set_index": last.set_index + 1, "weight": round_to_step(weight, step),
            "reps": reps, "rir_target": float(item.target_rir), "reason": reason}


def get_or_create_session(db: Session, template: WorkoutTemplate, on_date: date) -> WorkoutSession | None:
    open_session = db.scalar(select(WorkoutSession).where(
        WorkoutSession.template_id == template.id, WorkoutSession.status != "completed"
    ).order_by(WorkoutSession.scheduled_date))
    if open_session:
        return open_session
    existing = db.scalar(select(WorkoutSession).where(
        WorkoutSession.template_id == template.id, WorkoutSession.scheduled_date == on_date))
    if existing:
        return existing
    exercises = [e for e in template.exercises if e.active]
    if not exercises:
        return None
    week = resolve_week(db, template.user_id, on_date)
    counts = planned_counts(db, template.user_id, week)
    prior = db.scalar(select(TrainingWeek).where(
        TrainingWeek.user_id == template.user_id, TrainingWeek.week_start < week.week_start
    ).order_by(TrainingWeek.week_start.desc()))
    reentry = bool(prior and prior.phase_type == "deload" and not prior.missed_deload)
    session = WorkoutSession(user_id=template.user_id, template_id=template.id,
        template_name=template.name, muscle_group=template.muscle_group,
        scheduled_date=on_date, phase=1, phase_type=week.phase_type, week_id=week.id)
    db.add(session)
    db.flush()
    for e in exercises:
        movement = movement_for(db, e, template.user_id)
        weight, reps, action = prescription(db, e, week, reentry)
        db.add(SessionExercise(session_id=session.id, exercise_id=e.id,
            movement_id=movement.id, name=movement.name, position=e.position,
            sets_count=counts[e.id], target_weight=weight, target_reps=reps,
            min_reps=e.rep_min or e.medium_min, max_reps=e.rep_max or e.medium_max,
            target_rir=2.5 if reentry else week.target_rir,
            primary_group=movement.primary_group, secondary_groups=movement.secondary_groups,
            is_anchor=movement.is_anchor, action_label=action))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return db.scalar(select(WorkoutSession).where(
            WorkoutSession.template_id == template.id, WorkoutSession.scheduled_date == on_date))
    db.refresh(session)
    return session
