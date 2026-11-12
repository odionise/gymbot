from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import json
from statistics import mean, median

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .db import locked_row
from .models import Exercise, Mesocycle, Movement, MuscleTarget, SessionExercise, TrainingWeek, User, WeekOverride, WorkoutSession, WorkoutTemplate, utcnow
from .muscles import split_details, volume_group
from .history import comparable_history, history_id, slot_id, snapshot_key
from .recommendations import save_recommendation

PHASES = ("light", "medium", "heavy")  # historical labels


@dataclass(frozen=True)
class WeekState:
    """Known or projected week values, without an ORM identity or defaults."""
    id: str | None
    user_id: int
    mesocycle_id: str | None
    week_start: date
    week_number: int
    phase_type: str
    deload_reason: str | None
    is_postponed: bool
    missed_deload: bool
    feeling_beat_up: bool
    target_rir: float
    targets_json: str
    period_kind: str = "week"
    period_days: int = 7
    schedule_json: str = "[]"


@dataclass(frozen=True)
class WeekPlan:
    week: WeekState
    prior: WeekState | None
    before_prior: WeekState | None
    source: str
    new_block_number: int | None = None
    prior_missed_deload: bool | None = None


def week_state(item: TrainingWeek) -> WeekState:
    return WeekState(**{name: getattr(item, name) for name in WeekState.__dataclass_fields__})


def round_to_step(value: float, step: float) -> float:
    unit = Decimal(str(step))
    return float((Decimal(str(max(0, value))) / unit).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * unit)


def monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def vacation_override(db: Session, user_id: int, on_date: date) -> bool:
    user = db.get(User, user_id)
    if user and user.cycle_days is not None and user.cycle_anchor and on_date >= user.cycle_anchor:
        plan = project_cycle(db, user, on_date)
        return plan.week.week_start <= on_date and plan.week.phase_type == "vacation"
    return db.scalar(select(WeekOverride.id).where(
        WeekOverride.user_id == user_id, WeekOverride.week_start == monday(on_date),
        WeekOverride.kind == "vacation",
    )) is not None


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
    # The legacy assignment RIR is retained as recorded, including 0 and NULL.
    # New workout targets come from the phase/reentry policy instead.
    return movement


def completed_new(db: Session, user_id: int, start: date | None = None,
                  period: TrainingWeek | WeekState | None = None) -> list[WorkoutSession]:
    query = select(WorkoutSession).where(
        WorkoutSession.user_id == user_id, WorkoutSession.status == "completed",
        WorkoutSession.phase_type.is_not(None),
    )
    if period is not None and period.period_kind == "cycle":
        query = query.where(WorkoutSession.week_id == period.id)
    elif start is not None:
        query = query.where(WorkoutSession.actual_date >= start,
                            WorkoutSession.actual_date < start + timedelta(days=7))
    return list(db.scalars(query.options(
        selectinload(WorkoutSession.exercises).selectinload(SessionExercise.results),
        selectinload(WorkoutSession.exercises).selectinload(SessionExercise.exercise),
    ).order_by(WorkoutSession.completed_at.asc().nulls_first(), WorkoutSession.id)))


def week_stats(db: Session, user_id: int, start: date) -> dict:
    period = db.scalar(select(TrainingWeek).where(
        TrainingWeek.user_id == user_id, TrainingWeek.week_start == start))
    sessions = completed_new(db, user_id, start, period)
    hard, working = defaultdict(float), defaultdict(float)
    rir = []
    for session in sessions:
        for exercise in session.exercises:
            if exercise.kind != "strength" or exercise.skipped or not exercise.primary_group or exercise.primary_group == "Не назначено":
                continue
            weights = {volume_group(g): 0.5 for g in split_details(exercise.secondary_groups)}
            weights[volume_group(exercise.primary_group)] = 1.0
            groups = list(weights.items())
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
    active = list(db.scalars(select(Exercise).join(WorkoutTemplate).join(
        Movement, Exercise.movement_id == Movement.id,
    ).where(WorkoutTemplate.user_id == user_id, WorkoutTemplate.active.is_(True),
            Exercise.active.is_(True), Movement.kind == "strength")))
    selected = {(slot_id(e), history_id(e), e.movement_id, "strength") for e in active if e.movement_id}
    for session in completed_new(db, user_id):
        if session.phase_type != "accumulation":
            continue
        for item in session.exercises:
            sets = [r for r in item.results if r.is_working and r.rir_reported is not None]
            key = snapshot_key(item)
            if item.is_anchor and sets and key in selected:
                by_slot[key].append((float(sets[0].weight), mean(r.reps for r in sets)))
    return any(len(rows) >= 4 and len({weight for weight, _ in rows[-4:]}) == 1
               and all(rows[-i][1] < rows[-i-1][1] for i in (1, 2, 3))
               for rows in by_slot.values())


def missed_deload_value(db: Session, week: TrainingWeek | WeekState | None) -> bool | None:
    if not week or week.phase_type != "deload":
        return None
    actual = sum(week_stats(db, week.user_id, week.week_start)["working"].values())
    earlier = list(db.scalars(select(TrainingWeek).where(
        TrainingWeek.user_id == week.user_id, TrainingWeek.week_start < week.week_start,
        TrainingWeek.phase_type == "accumulation", TrainingWeek.period_kind == week.period_kind,
    ).order_by(TrainingWeek.week_start.desc()).limit(2)))
    baselines = [sum(week_stats(db, week.user_id, item.week_start)["working"].values()) for item in earlier]
    return bool(baselines and median(baselines) > 0 and actual >= 0.8 * median(baselines))


def mark_missed_deload(db: Session, week: TrainingWeek | None) -> None:
    value = missed_deload_value(db, week)
    if value is not None:
        week.missed_deload = value


def cycle_schedule(week: TrainingWeek | WeekState) -> list[dict]:
    return sorted(json.loads(week.schedule_json or "[]"),
                  key=lambda slot: (slot["day"], slot["template_id"]))


def cycle_sessions(db: Session, week: TrainingWeek | WeekState) -> list[WorkoutSession]:
    return list(db.scalars(select(WorkoutSession).where(
        WorkoutSession.user_id == week.user_id, WorkoutSession.week_id == week.id)))


def cycle_complete(db: Session, week: TrainingWeek | WeekState, on_date: date) -> bool:
    if week.phase_type == "vacation":
        return on_date >= week.week_start + timedelta(days=week.period_days)
    completed = {(item.cycle_day, item.template_id) for item in cycle_sessions(db, week)
                 if item.status == "completed"}
    schedule = cycle_schedule(week)
    return bool(schedule) and all((slot["day"], slot["template_id"]) in completed for slot in schedule)


def next_cycle_start(db: Session, week: TrainingWeek | WeekState) -> date:
    earliest = week.week_start + timedelta(days=week.period_days)
    schedule = cycle_schedule(week)
    completed = [item for item in cycle_sessions(db, week) if item.status == "completed"]
    if not schedule or not completed:
        return earliest
    final_day = max(slot["day"] for slot in schedule)
    last_actual = max((item.actual_date or item.scheduled_date) for item in completed)
    return max(earliest, last_actual + timedelta(days=week.period_days - final_day + 1))


def project_cycle(db: Session, user: User, on_date: date) -> WeekPlan:
    latest = db.scalar(select(TrainingWeek).where(
        TrainingWeek.user_id == user.telegram_id, TrainingWeek.period_kind == "cycle",
        TrainingWeek.week_start <= on_date,
    ).order_by(TrainingWeek.week_start.desc()))
    if latest and not cycle_complete(db, latest, on_date):
        prior_item = db.scalar(select(TrainingWeek).where(
            TrainingWeek.user_id == user.telegram_id, TrainingWeek.period_kind == "cycle",
            TrainingWeek.week_start < latest.week_start,
        ).order_by(TrainingWeek.week_start.desc()))
        before_item = db.scalar(select(TrainingWeek).where(
            TrainingWeek.user_id == user.telegram_id, TrainingWeek.period_kind == "cycle",
            TrainingWeek.week_start < prior_item.week_start,
        ).order_by(TrainingWeek.week_start.desc())) if prior_item else None
        return WeekPlan(week_state(latest), week_state(prior_item) if prior_item else None,
                        week_state(before_item) if before_item else None, "saved")
    last_training = (latest if latest and latest.phase_type != "vacation" else
                     db.scalar(select(TrainingWeek).where(
                         TrainingWeek.user_id == user.telegram_id,
                         TrainingWeek.period_kind == "cycle",
                         TrainingWeek.phase_type != "vacation",
                         TrainingWeek.week_start < latest.week_start,
                     ).order_by(TrainingWeek.week_start.desc())) if latest else None)
    prior = week_state(last_training) if last_training else None
    start = max(user.cycle_anchor, next_cycle_start(db, latest)) if latest else user.cycle_anchor
    before_item = db.scalar(select(TrainingWeek).where(
        TrainingWeek.user_id == user.telegram_id, TrainingWeek.period_kind == "cycle",
        TrainingWeek.week_start < prior.week_start,
    ).order_by(TrainingWeek.week_start.desc())) if prior else None
    before_prior = week_state(before_item) if before_item else None
    missed = missed_deload_value(db, prior)
    if missed is not None:
        prior = replace(prior, missed_deload=missed)
    number = 1 if prior is None or prior.phase_type == "deload" else prior.week_number + 1
    override_kind = user.next_cycle_override
    if override_kind == "vacation":
        phase, reason = "vacation", None
        number = prior.week_number if prior else 0
    else:
        phase = "deload" if override_kind == "deload" or number == 4 else "accumulation"
        reason = "manual" if override_kind == "deload" else "scheduled" if phase == "deload" else None
    saved_targets = {item.muscle_group: item for item in db.scalars(select(MuscleTarget).where(
        MuscleTarget.user_id == user.telegram_id))}
    targets = {group: [item.min_sets, item.max_sets, item.cap_sets]
               for group, item in saved_targets.items()}
    templates = list(db.scalars(select(WorkoutTemplate).where(
        WorkoutTemplate.user_id == user.telegram_id, WorkoutTemplate.active.is_(True))))
    schedule = sorted(({"day": day, "template_id": template.id}
                       for template in templates for day in json.loads(template.cycle_days_json or "[]")),
                      key=lambda slot: (slot["day"], slot["template_id"]))
    new_block = None
    if number == 1 and (prior is None or prior.phase_type == "deload"):
        last_block = db.scalar(select(Mesocycle.block_number).where(
            Mesocycle.user_id == user.telegram_id).order_by(Mesocycle.block_number.desc())) or 0
        new_block = last_block + 1
    week = WeekState(None, user.telegram_id, None if new_block else prior.mesocycle_id if prior else latest.mesocycle_id if latest else None,
                     start, number, phase, reason, False, False, False,
                     4 if phase == "deload" else 2 if phase == "accumulation" else 0,
                     json.dumps(targets, ensure_ascii=False), "cycle", user.cycle_days,
                     json.dumps(schedule))
    return WeekPlan(week, prior, before_prior, "calculated", new_block, missed)


def project_due_cycle_slot(db: Session, user: User, on_date: date) -> tuple[dict, date] | None:
    if user.cycle_days is None or user.cycle_anchor is None or on_date < user.cycle_anchor:
        return None
    plan = project_cycle(db, user, on_date)
    week = plan.week
    if week.week_start > on_date:
        return None
    if week.phase_type == "vacation":
        return None
    completed = {(item.cycle_day, item.template_id): item for item in cycle_sessions(db, week)
                 if item.status == "completed"} if week.id else {}
    prior_slot = None
    for slot in cycle_schedule(week):
        key = (slot["day"], slot["template_id"])
        if key in completed:
            prior_slot = (slot, completed[key])
            continue
        due = week.week_start + timedelta(days=slot["day"] - 1)
        if prior_slot:
            previous, session = prior_slot
            due = max(due, (session.actual_date or session.scheduled_date)
                      + timedelta(days=slot["day"] - previous["day"]))
        return (slot, due) if due <= on_date else None
    return None


def due_cycle_slot(db: Session, user: User, on_date: date) -> tuple[dict, date] | None:
    """Writable calendar path; persist a selected vacation before returning."""
    if user.cycle_days is not None and user.cycle_anchor and on_date >= user.cycle_anchor:
        plan = project_cycle(db, user, on_date)
        if plan.week.week_start <= on_date and plan.week.phase_type == "vacation" and plan.source == "calculated":
            resolve_week(db, user.telegram_id, on_date)
            db.commit()
    return project_due_cycle_slot(db, user, on_date)


def project_week(db: Session, user_id: int, on_date: date) -> WeekPlan:
    """Resolve the same calendar decision as creation, using only SELECTs.

    A newly evaluated missed-deload flag belongs to this projected context. It
    must affect counts and reentry without mutating the persisted prior week.
    Missing calendar weeks are not simulated as hypothetical workouts.
    """
    user = db.get(User, user_id)
    if user.cycle_days is not None and user.cycle_anchor is not None and on_date >= user.cycle_anchor:
        return project_cycle(db, user, on_date)
    start = monday(on_date)
    existing = db.scalar(select(TrainingWeek).where(
        TrainingWeek.user_id == user_id, TrainingWeek.week_start == start))
    prior_item = db.scalar(select(TrainingWeek).where(
        TrainingWeek.user_id == user_id, TrainingWeek.week_start < start,
        TrainingWeek.phase_type != "vacation",
    ).order_by(TrainingWeek.week_start.desc()))
    prior = week_state(prior_item) if prior_item else None
    before_item = db.scalar(select(TrainingWeek).where(
        TrainingWeek.user_id == user_id, TrainingWeek.week_start < prior.week_start,
        TrainingWeek.phase_type != "vacation",
    ).order_by(TrainingWeek.week_start.desc())) if prior else None
    before_prior = week_state(before_item) if before_item else None
    if existing:
        return WeekPlan(week_state(existing), prior, before_prior, "saved")
    override = db.scalar(select(WeekOverride).where(WeekOverride.user_id == user_id, WeekOverride.week_start == start))
    if override and override.kind == "vacation":
        week = WeekState(None, user_id, prior.mesocycle_id if prior else None, start,
                         prior.week_number if prior else 0, "vacation", None,
                         False, False, False, 0, "{}")
        return WeekPlan(week, prior, before_prior, "calculated", None if prior else 1)
    missed = missed_deload_value(db, prior)
    if missed is not None:
        prior = replace(prior, missed_deload=missed)
    last_stats = week_stats(db, user_id, start - timedelta(days=7))
    avg_rir = last_stats["avg_rir"]
    decline = declining_anchor(db, user_id)
    fatigue = (avg_rir is not None and avg_rir < 1) or decline
    new_block = None
    if prior is None or (prior.phase_type == "deload" and not prior.missed_deload) or (start - prior.week_start).days > 35:
        number = 1
        new_block = db.get(Mesocycle, prior.mesocycle_id).block_number + 1 if prior else 1
    else:
        number = prior.week_number + 1
        if number > 5 or (number == 5 and not prior.is_postponed and not prior.missed_deload):
            new_block = db.get(Mesocycle, prior.mesocycle_id).block_number + 1
            number = 1
    scheduled = number >= 4
    postpone = (scheduled and number == 4 and not fatigue and avg_rir is not None
                and avg_rir >= 2 and not (prior and prior.feeling_beat_up))
    phase = "deload" if override or fatigue or (scheduled and not postpone) else "accumulation"
    reason = "manual" if override else "auto" if fatigue else "scheduled" if phase == "deload" else None
    if override:
        postpone = False
    saved_targets = {item.muscle_group: item for item in db.scalars(select(MuscleTarget).where(
        MuscleTarget.user_id == user_id))}
    targets = {group: [item.min_sets, item.max_sets, item.cap_sets]
               for group, item in saved_targets.items()}
    week = WeekState(None, user_id, None if new_block else prior.mesocycle_id, start, number,
                     phase, reason, postpone, False, False, 4 if phase == "deload" else 2,
                     json.dumps(targets, ensure_ascii=False))
    return WeekPlan(week, prior, before_prior, "calculated", new_block, missed)


def resolve_week(db: Session, user_id: int, on_date: date) -> TrainingWeek:
    """Persist a shared week decision only on the existing write paths."""
    locked_row(db, User, User.telegram_id == user_id)
    plan = project_week(db, user_id, on_date)
    if plan.source == "saved":
        return db.get(TrainingWeek, plan.week.id)
    if plan.prior_missed_deload is not None:
        db.get(TrainingWeek, plan.prior.id).missed_deload = plan.prior_missed_deload
    values = {name: getattr(plan.week, name) for name in WeekState.__dataclass_fields__ if name != "id"}
    if plan.new_block_number is not None:
        mesocycle = Mesocycle(user_id=user_id, block_number=plan.new_block_number, start_week=plan.week.week_start)
        db.add(mesocycle)
        db.flush()
        values["mesocycle_id"] = mesocycle.id
    week = TrainingWeek(**values)
    db.add(week)
    db.flush()
    if week.period_kind == "cycle":
        db.get(User, user_id).next_cycle_override = None
    return week


def latest_accumulation(db: Session, exercise_id: str) -> list[SessionExercise]:
    exercise = db.get(Exercise, exercise_id)
    if exercise is None:
        return []
    return list(db.scalars(comparable_history(db, exercise).where(
        WorkoutSession.status == "completed",
        WorkoutSession.phase_type == "accumulation",
        SessionExercise.skipped.is_(False),
    ).order_by(WorkoutSession.completed_at.desc().nulls_last(), WorkoutSession.id.desc()).limit(3)))


def prescription_details(db: Session, exercise: Exercise, week: TrainingWeek, reentry: bool) -> dict:
    """Calculate targets and evidence together so the explanation cannot drift."""
    minimum = exercise.rep_min or exercise.medium_min
    maximum = exercise.rep_max or exercise.medium_max
    step = float(exercise.weight_step)
    history = latest_accumulation(db, exercise.id)
    evidence = []
    for item in history:
        working = [r for r in item.results if r.is_working]
        evidence.append({
            "session_id": item.session_id, "session_exercise_id": item.id,
            "date": (item.session.actual_date or item.session.scheduled_date).isoformat(),
            "completed_at": item.session.completed_at.isoformat() if item.session.completed_at else None,
            "base_weight": float(working[0].weight if working else item.target_weight),
            "weight_source": "first_working" if working else "planned", "planned_sets": item.sets_count,
            "working_sets": [{"set_index": r.set_index, "weight": float(r.weight), "reps": r.reps,
                              "rir": float(r.rir_reported) if r.rir_reported is not None else None}
                             for r in working],
        })
    raw_median = median(row["base_weight"] for row in evidence) if evidence else None
    base = round_to_step(raw_median if raw_median is not None else float(exercise.medium_weight), step)
    weight, reps, reps_median = base, minimum, None
    weight_code, reps_code = "start", "lower_bound"
    action = "Стартовый вес"
    weight_reason = "Нет завершённых обычных занятий этой базы: стартовый вес округлён к шагу."
    reps_reason = "Нижняя граница настроенного диапазона."
    if history:
        last = history[0]
        results = [r for r in last.results if r.is_working]
        weight_code = "median"
        weight_reason = "Медиана первых рабочих весов выбранных занятий, округлённая к шагу. Для занятия без рабочих подходов используется его плановый вес."
        if week.phase_type == "deload":
            weight_code, action = "deload", "Легкая неделя: вес без повышения"
            weight_reason += " Лёгкая неделя: повышения нет."
        elif reentry:
            weight_code, action = "reentry", "Возвращение после легкой недели: вес без повышения"
            weight_reason += " Возвращение: повышения нет."
        elif results and len(results) == last.sets_count and all(
                r.reps >= maximum and r.rir_reported is not None and float(r.rir_reported) >= 1 for r in results):
            weight = round_to_step(base + step, step)
            weight_code, action = "increase_step", "Верх диапазона: +1 шаг веса"
            weight_reason += " В последнем занятии все назначенные рабочие подходы достигли верха диапазона с ПДО ≥ 1: плюс один шаг. Равенство весов подходов не требуется."
        elif results and all(r.rir_reported is not None and float(r.rir_reported) >= 1 for r in results):
            reps_median = median(r.reps for r in results)
            # Only the automatic target is bounded. Facts and explicit manual
            # targets may legitimately be outside the configured rep range.
            reps = max(minimum, min(maximum, round(reps_median) + 1))
            reps_code, action = "increase_reps", "Добавить повторение"
            reps_reason = "Медиана рабочих повторов последнего занятия округлена к ближайшему целому (половины к чётному), плюс один; результат ограничен настроенным диапазоном."
        else:
            reps_code, action = "insufficient_rir", "Сохранить вес: проверить восстановление"
            reps_reason = "Нет рабочих результатов либо хотя бы один ПДО неизвестен или ниже 1: нижняя граница повторов."
    return {"weight_value": weight, "reps_value": reps, "action": action, "history": evidence,
            "weight": {"reason_code": weight_code, "reason": weight_reason, "median": raw_median,
                       "rounded_base": base, "step": step},
            "reps": {"reason_code": reps_code, "reason": reps_reason, "median": reps_median}}


def prescription(db: Session, exercise: Exercise, week: TrainingWeek, reentry: bool) -> tuple[float, int, str]:
    result = prescription_details(db, exercise, week, reentry)
    return result["weight_value"], result["reps_value"], result["action"]


def recommendation_context(db: Session, exercise: Exercise, week: TrainingWeek, reentry: bool, sets: dict) -> dict:
    result = prescription_details(db, exercise, week, reentry)
    source = "deload" if week.phase_type == "deload" else "reentry" if reentry else "accumulation"
    rir = 4.0 if source == "deload" else 2.5 if source == "reentry" else float(week.target_rir)
    reason = {"deload": "Лёгкая фаза: ПДО 4, в том числе при двух лёгких неделях подряд.",
              "reentry": "Возвращение в обычную фазу после непропущенной лёгкой недели: ПДО 2,5.",
              "accumulation": "Цель обычной недели; настройка упражнения на неё не влияет."}[source]
    return {"version": 1, "rules_version": "2", "created_at": utcnow().isoformat(),
            "inputs": {"start_weight": float(exercise.medium_weight), "weight_step": float(exercise.weight_step),
                       "rep_min": exercise.rep_min or exercise.medium_min, "rep_max": exercise.rep_max or exercise.medium_max,
                       "base_sets": exercise.sets_count},
            "history": result["history"], "weight": result["weight"], "reps": result["reps"],
            "sets": sets, "rir": {"source": source, "reason": reason},
            "calculated": {"weight": result["weight_value"], "reps": result["reps_value"],
                           "sets_count": sets["value"], "rir": rir},
            "manual_override": {}, "action_label": result["action"]}


def planned_counts(db: Session, user_id: int, week: TrainingWeek | WeekState, details: dict | None = None,
                   *, week_plan: WeekPlan | None = None,
                   movement_map: dict[str, Movement] | None = None) -> dict[str, int]:
    templates = list(db.scalars(select(WorkoutTemplate).where(
        WorkoutTemplate.user_id == user_id, WorkoutTemplate.active.is_(True))))
    frequencies = Counter(slot["template_id"] for slot in cycle_schedule(week)) if week.period_kind == "cycle" else None
    if frequencies is not None:
        templates = [template for template in templates if frequencies[template.id]]
    def lookup(e: Exercise) -> Movement:
        return movement_map[e.id] if movement_map is not None else movement_for(db, e, user_id)
    exercises = [e for t in templates for e in t.exercises if e.active and lookup(e).kind == "strength"]
    counts = {e.id: e.sets_count for e in exercises}
    trace = {e.id: {"base": e.sets_count, "reason_code": "base",
                    "reason": "Базовое число подходов из программы."} for e in exercises}
    def explain(code: str, reason: str) -> None:
        for item in trace.values():
            item.update(reason_code=code, reason=reason)
    movements = {e.id: lookup(e) for e in exercises}
    def volume(group: str) -> float:
        return sum(counts[e.id] * (frequencies[e.template_id] if frequencies is not None else 1) *
                   (1 if volume_group(movements[e.id].primary_group) == group else
                   0.5 if group in {volume_group(g) for g in split_details(movements[e.id].secondary_groups)} else 0)
                   for e in exercises)
    groups = ({volume_group(m.primary_group) for m in movements.values() if m.primary_group != "Не назначено"}
              | {volume_group(group) for m in movements.values() for group in split_details(m.secondary_groups)})
    targets = json.loads(week.targets_json or "{}")
    default_cap = db.get(User, user_id).volume_cap
    scale = week.period_days / 7 if week.period_kind == "cycle" else 1
    def cap(group: str, deload: bool) -> int:
        return max(1, round((8 if deload else targets.get(group, [12, 18, default_cap])[2]) * scale))
    def enforce_limits(deload: bool = False) -> dict[str, int]:
        before_counts = counts.copy()
        before_volumes = {group: volume(group) for group in groups}
        for group in sorted(groups):
            limit = cap(group, deload)
            candidates = sorted((e for e in exercises if volume_group(movements[e.id].primary_group) == group
                                 or group in {volume_group(g) for g in split_details(movements[e.id].secondary_groups)}),
                                 key=lambda e: (movements[e.id].is_anchor, -counts[e.id], slot_id(e)))
            while volume(group) > limit and any(counts[e.id] > 1 for e in candidates):
                candidate = next(e for e in candidates if counts[e.id] > 1)
                counts[candidate.id] -= 1
        if details is not None:
            for e in exercises:
                movement = movements[e.id]
                own_groups = {volume_group(g) for g in (movement.primary_group, *split_details(movement.secondary_groups))} & groups
                item = {**trace[e.id], "value": counts[e.id], "before_limits": before_counts[e.id],
                        "limited": counts[e.id] != before_counts[e.id],
                        "limits": [{"group": group, "cap": cap(group, deload),
                                    "before": before_volumes[group], "after": volume(group)} for group in sorted(own_groups)]}
                if item["limited"]:
                    item["reason"] += " Число уменьшено до предела нагрузки мышц за цикл; учитываются также вторичные мышцы."
                details[e.id] = item
        return counts
    if week.phase_type == "deload":
        counts = {e.id: max(1, round(e.sets_count * 0.5)) for e in exercises}
        explain("deload", "Лёгкий цикл: половина базовых подходов с округлением к ближайшему целому (половины к чётному), минимум один; предел нагрузки пересчитан на длину цикла.")
        return enforce_limits(deload=True)
    prior = week_plan.prior if week_plan is not None else db.scalar(select(TrainingWeek).where(
        TrainingWeek.user_id == user_id, TrainingWeek.week_start < week.week_start,
        TrainingWeek.phase_type != "vacation", TrainingWeek.period_kind == week.period_kind,
    ).order_by(TrainingWeek.week_start.desc()))
    if prior and prior.phase_type == "deload" and not prior.missed_deload:
        counts = {e.id: min(e.sets_count, max(1, round(e.sets_count * 0.5) + 1)) for e in exercises}
        explain("reentry", "Возвращение: половина базовых подходов с округлением плюс один, не больше базового числа.")
        return enforce_limits()
    if week.week_number < 2 or not prior:
        explain("base", "Начало блока или нет предыдущего завершённого цикла: базовые подходы.")
        return enforce_limits()
    before_prior = week_plan.before_prior if week_plan is not None else db.scalar(select(TrainingWeek).where(
        TrainingWeek.user_id == user_id, TrainingWeek.week_start < prior.week_start,
        TrainingWeek.phase_type != "vacation", TrainingWeek.period_kind == week.period_kind,
    ).order_by(TrainingWeek.week_start.desc()))
    if week.week_number == 2 and before_prior and before_prior.phase_type == "deload" and not before_prior.missed_deload:
        explain("reentry_hold", "Вторая неделя после разгрузки: базовые подходы без недельной прибавки.")
        return enforce_limits()
    if prior.feeling_beat_up:
        if before_prior and before_prior.feeling_beat_up:
            counts = {e.id: max(1, round(e.sets_count * 0.75)) for e in exercises}
            explain("recovery_reduce", "Две недели подряд отмечено тяжело/болит: 75% базовых подходов с округлением, минимум один.")
        else:
            explain("recovery_hold", "На предыдущей неделе отмечено тяжело/болит: базовые подходы без роста.")
        return enforce_limits()
    stats = week_stats(db, user_id, prior.week_start)
    completed_templates = {(s.template_id, s.cycle_day) for s in stats["sessions"]} if frequencies is not None else {s.template_id for s in stats["sessions"]}
    decline = declining_anchor(db, user_id)
    missing_days = ([slot for slot in cycle_schedule(week_plan.prior if week_plan and week_plan.prior else prior)
                     if (slot["template_id"], slot["day"]) not in completed_templates]
                    if frequencies is not None else [t.id for t in templates if t.id not in completed_templates])
    if stats["avg_rir"] is None or stats["avg_rir"] < 1 or decline or missing_days:
        explain("insufficient_week", "Прибавка за цикл не разрешена: неизвестен/низок средний ПДО, снижается якорное упражнение или завершены не все занятия. Используются базовые подходы.")
        for item in trace.values():
            item["checks"] = {"avg_rir": stats["avg_rir"], "declining_anchor": decline, "missing_days": missing_days}
        return enforce_limits()
    selected_ids = {(slot_id(e), history_id(e), e.movement_id, "strength"): e.id for e in exercises}
    for session in stats["sessions"]:
        for item in session.exercises:
            current_id = selected_ids.get(snapshot_key(item))
            if current_id is not None and not item.skipped:
                counts[current_id] = item.sets_count
                trace[current_id].update(reason_code="carry", reason="Сохранено число подходов сопоставимого занятия предыдущей недели.",
                                         previous_sets=item.sets_count, previous_session_id=session.id)
    by_group = defaultdict(list)
    for e in exercises:
        movement = movements[e.id]
        if movement.primary_group != "Не назначено":
            by_group[volume_group(movement.primary_group)].append((e, movement))
    for group, options in by_group.items():
        cap_value = cap(group, False)
        options.sort(key=lambda pair: (not pair[1].is_anchor, pair[0].position, slot_id(pair[0])))
        if volume(group) < cap_value:
            candidate = options[(week.week_number - 2) % len(options)][0]
            previous_count = counts[candidate.id]
            counts[candidate.id] = min(12, counts[candidate.id] + 1)
            if counts[candidate.id] > previous_count:
                trace[candidate.id].update(reason_code="progression", reason="Условия роста за цикл выполнены: выбранному упражнению основной мышцы добавлен один подход, максимум 12.")
            else:
                trace[candidate.id].update(reason_code="max_sets", reason="Недельные условия роста выполнены, но упражнение уже достигло предела 12 подходов: прибавки нет.")
    return enforce_limits()


def is_reentry(db: Session, user_id: int, week: TrainingWeek | WeekState, week_plan: WeekPlan | None = None) -> bool:
    prior = week_plan.prior if week_plan is not None else db.scalar(select(TrainingWeek).where(
        TrainingWeek.user_id == user_id, TrainingWeek.week_start < week.week_start,
        TrainingWeek.phase_type != "vacation", TrainingWeek.period_kind == week.period_kind,
    ).order_by(TrainingWeek.week_start.desc()))
    return bool(week.phase_type == "accumulation" and prior and prior.phase_type == "deload" and not prior.missed_deload)


def next_set_suggestion(item: SessionExercise, step: float) -> dict | None:
    if item.kind != "strength":
        return None
    results = sorted((r for r in item.results if r.is_working), key=lambda r: r.set_index)
    if not results or len(results) >= item.sets_count:
        return None
    last = results[-1]
    if last.set_index >= item.sets_count:
        return None
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
    elif difference >= 2 and item.session.phase_type == "deload":
        reason = "Лёгкая неделя: повышение веса отключено"
    else:
        reason = "Вес в целевом коридоре"
    reps = max(item.min_reps, min(item.max_reps, last.reps - 1 if difference <= -1 else item.target_reps))
    return {"set_index": last.set_index + 1, "weight": round_to_step(weight, step),
            "reps": reps, "rir_target": float(item.target_rir), "reason": reason,
            "basis": {"set_index": last.set_index, "weight": float(last.weight), "reps": last.reps,
                      "rir_reported": float(last.rir_reported), "target_rir": float(item.target_rir),
                      "weight_step": step, "rir_difference": difference}}


def get_or_create_session(db: Session, template: WorkoutTemplate, on_date: date,
                          cycle_day: int | None = None) -> WorkoutSession | None:
    # All write paths acquire the same user's lock first. Different days can
    # otherwise race to insert their common training week/mesocycle.
    locked_row(db, User, User.telegram_id == template.user_id)
    user = db.get(User, template.user_id)
    if user.cycle_days is None and vacation_override(db, template.user_id, on_date):
        return None
    template = db.scalar(select(WorkoutTemplate).where(
        WorkoutTemplate.id == template.id, WorkoutTemplate.active.is_(True),
    ).with_for_update().execution_options(populate_existing=True))
    if template is None:
        return None
    db.expire(template, ["exercises"])
    week = resolve_week(db, template.user_id, on_date)
    if week.phase_type == "vacation":
        return None
    if week.period_kind == "cycle" and cycle_day is None:
        return None
    open_query = select(WorkoutSession).where(
        WorkoutSession.template_id == template.id, WorkoutSession.status != "completed")
    if week.period_kind == "cycle":
        open_query = open_query.where(WorkoutSession.week_id == week.id,
                                      WorkoutSession.cycle_day == cycle_day)
    open_session = db.scalar(open_query.order_by(WorkoutSession.scheduled_date))
    if open_session:
        return open_session
    existing = db.scalar(select(WorkoutSession).where(
        WorkoutSession.template_id == template.id, WorkoutSession.scheduled_date == on_date))
    if existing:
        return existing
    exercises = [e for e in template.exercises if e.active]
    if not exercises:
        return None
    count_details = {}
    planned_counts(db, template.user_id, week, count_details)
    reentry = is_reentry(db, template.user_id, week)
    session = WorkoutSession(user_id=template.user_id, template_id=template.id,
        template_name=template.name, muscle_group=template.muscle_group,
        scheduled_date=on_date, phase=1, phase_type=week.phase_type, week_id=week.id,
        cycle_day=cycle_day)
    db.add(session)
    db.flush()
    for e in exercises:
        movement = movement_for(db, e, template.user_id)
        timed = movement.kind != "strength"
        context = None if timed else recommendation_context(db, e, week, reentry, count_details[e.id])
        calculated = context["calculated"] if context else {"weight": 0, "reps": 0, "sets_count": 0, "rir": None}
        item = SessionExercise(session_id=session.id, exercise_id=e.id,
            movement_id=movement.id, name=movement.name, position=e.position,
            kind=movement.kind, target_duration_minutes=e.duration_minutes if timed else None,
            weight_step=None if timed else e.weight_step,
            sets_count=calculated["sets_count"], target_weight=calculated["weight"], target_reps=calculated["reps"],
            min_reps=0 if timed else (e.rep_min or e.medium_min), max_reps=0 if timed else (e.rep_max or e.medium_max),
            target_rir=calculated["rir"],
            primary_group=movement.primary_group, secondary_groups=movement.secondary_groups,
            is_anchor=movement.is_anchor, action_label=context["action_label"] if context else "Цель по времени")
        if context is not None:
            save_recommendation(item, context)
        db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return db.scalar(select(WorkoutSession).where(
            WorkoutSession.template_id == template.id, WorkoutSession.scheduled_date == on_date))
    db.refresh(session)
    return session
