"""Read-only projection of one new workout; never an ORM workout instance."""

from datetime import date, timedelta
from math import isfinite
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .history import history_id, slot_id
from .models import Movement, User, WorkoutSession, WorkoutTemplate, utcnow
from .muscles import ALL_DETAILED_GROUPS
from .planning import is_reentry, monday, planned_counts, project_due_cycle_slot, project_week, recommendation_context, vacation_override


def configured_movements(db: Session, user_id: int, selected: WorkoutTemplate) -> tuple[dict, list]:
    """Validate all assignments which can influence the shared volume budget.

    This deliberately does not call movement_for: an absent legacy link must be
    explained instead of creating a movement during a GET request.
    """
    mapping, blockers = {}, []
    selected_movements = [db.get(Movement, item.movement_id) for item in selected.exercises
                          if item.active and item.movement_id]
    # A minutes-only workout has no muscle-volume targets. Unrelated legacy
    # days cannot affect its minutes and must not unnecessarily block it.
    needs_volume = any(item is not None and item.kind == "strength" for item in selected_movements)
    templates = db.scalars(select(WorkoutTemplate).where(
        WorkoutTemplate.user_id == user_id, WorkoutTemplate.active.is_(True),
    ).order_by(WorkoutTemplate.id)) if needs_volume else [selected]
    for template in templates:
        for exercise in template.exercises:
            if not exercise.active:
                continue
            movement = db.get(Movement, exercise.movement_id) if exercise.movement_id else None
            message = None
            if movement is None or movement.user_id != user_id or not movement.active:
                message = "У назначения нет доступного собственного движения. Уточните его в программе."
            elif movement.kind not in ("strength", "cardio", "stretch", "other_timed"):
                message = "Тип движения неизвестен; расчёт не может подменить его силовым или временным типом."
            elif movement.kind == "strength":
                if movement.primary_group not in ALL_DETAILED_GROUPS or not 1 <= exercise.sets_count <= 12:
                    message = "Для расчёта общего объёма уточните основную мышцу и число подходов."
                elif template.id == selected.id:
                    low, high = exercise.rep_min or exercise.medium_min, exercise.rep_max or exercise.medium_max
                    weight, step = float(exercise.medium_weight), float(exercise.weight_step)
                    if (not isfinite(weight) or not 0 <= weight <= 1000 or not isfinite(step)
                            or not 0 < step <= 100 or not 1 <= low <= high <= 50):
                        message = "Уточните стартовый вес, шаг и диапазон повторов упражнения."
            elif template.id == selected.id and (exercise.duration_minutes is None or not 1 <= exercise.duration_minutes <= 600):
                message = "Для упражнения на время укажите положительную длительность в минутах."
            if message:
                blockers.append({"code": "needs_configuration", "message": message,
                                 "template_id": template.id, "exercise_id": exercise.id})
            else:
                mapping[exercise.id] = movement
    return mapping, blockers


def preview_session(db: Session, user_id: int, template_id: str, on_date: date) -> dict:
    user = db.get(User, user_id)
    template = db.scalar(select(WorkoutTemplate).where(
        WorkoutTemplate.id == template_id, WorkoutTemplate.user_id == user_id,
        WorkoutTemplate.active.is_(True),
    )) if user else None
    if template is None:
        raise HTTPException(404, "День программы не найден")
    now = utcnow()
    local_today = now.astimezone(ZoneInfo(user.timezone)).date()
    if not local_today <= on_date <= monday(local_today) + timedelta(days=13):
        raise HTTPException(422, "Выберите сегодня или будущую дату до конца следующей недели по вашему часовому поясу")
    plan = project_week(db, user_id, on_date)
    week = plan.week
    result = {"state": "blocked", "template_id": template.id, "on_date": on_date.isoformat(),
              "timezone": user.timezone, "computed_at": now.isoformat(), "provisional": True, "persisted": False,
              "week": {"week_start": week.week_start.isoformat(), "week_number": week.week_number,
                       "phase_type": week.phase_type, "deload_reason": week.deload_reason,
                       "is_postponed": week.is_postponed, "missed_deload": week.missed_deload, "source": plan.source},
              "exercises": [], "existing_session": None, "blocking_reasons": []}
    if week.phase_type == "vacation" or vacation_override(db, user_id, on_date):
        if week.phase_type != "vacation":
            # An old inconsistent saved phase cannot bypass an explicit holiday.
            # This is a projection only; preserve the recorded week/snapshots.
            result["week"].update(phase_type="vacation", deload_reason=None, is_postponed=False, source="calculated")
        result["blocking_reasons"] = [{"code": "vacation", "message": "На выбранной неделе отпуск: новый план не создаётся."}]
        return result
    existing = db.scalar(select(WorkoutSession).where(
        WorkoutSession.template_id == template.id, WorkoutSession.user_id == user_id,
        WorkoutSession.status != "completed",
    ).order_by(WorkoutSession.scheduled_date, WorkoutSession.id))
    if existing is None:
        existing = db.scalar(select(WorkoutSession).where(
            WorkoutSession.template_id == template.id, WorkoutSession.user_id == user_id,
            WorkoutSession.scheduled_date == on_date,
        ))
    if existing is not None:
        result.update(state="existing", existing_session={"id": existing.id,
                      "scheduled_date": existing.scheduled_date.isoformat(), "status": existing.status})
        return result
    if user.cycle_days is not None and user.cycle_anchor and on_date >= user.cycle_anchor:
        due = project_due_cycle_slot(db, user, on_date)
        if due is None or due[0]["template_id"] != template_id or due[1] != on_date:
            result["blocking_reasons"] = [{"code": "cycle_schedule",
                "message": "Сначала завершите предыдущее занятие цикла или выберите дату очередного занятия."}]
            return result
    exercises = [item for item in template.exercises if item.active]
    if not exercises:
        result["blocking_reasons"] = [{"code": "empty_program", "message": "В этом дне программы нет активных упражнений."}]
        return result
    movements, blockers = configured_movements(db, user_id, template)
    if blockers:
        result["blocking_reasons"] = blockers
        return result
    details = {}
    if any(movements[item.id].kind == "strength" for item in exercises):
        planned_counts(db, user_id, week, details, week_plan=plan, movement_map=movements)
    reentry = is_reentry(db, user_id, week, plan)
    for exercise in exercises:
        movement = movements[exercise.id]
        timed = movement.kind != "strength"
        context = None if timed else recommendation_context(db, exercise, week, reentry, details[exercise.id])
        if context is not None:
            # This is the creation time of the transient explanation only.
            context["created_at"] = result["computed_at"]
        targets = context["calculated"] if context else {"weight": None, "reps": None, "sets_count": None, "rir": None}
        result["exercises"].append({
            "exercise_id": exercise.id, "slot_id": slot_id(exercise), "history_id": history_id(exercise),
            "movement_id": movement.id, "name": movement.name, "kind": movement.kind, "position": exercise.position,
            "sets_count": targets["sets_count"], "target_weight": targets["weight"], "target_reps": targets["reps"],
            "target_rir": targets["rir"], "target_duration_minutes": exercise.duration_minutes if timed else None,
            "recommendation": context,
        })
    result["state"] = "ready"
    return result
