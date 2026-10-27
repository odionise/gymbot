from .models import Exercise, Movement, SessionExercise, WorkoutSession, WorkoutTemplate
from .muscles import split_details
from .planning import PHASES, next_set_suggestion


def movement_dict(item: Movement) -> dict:
    return {"id": item.id, "name": item.name, "kind": item.kind, "primary_group": item.primary_group,
            "secondary_groups": split_details(item.secondary_groups), "is_anchor": item.is_anchor}


def exercise_dict(item: Exercise) -> dict:
    return {
        "id": item.id, "name": item.name, "position": item.position,
        "sets_count": item.sets_count, "medium_weight": float(item.medium_weight),
        "weight_step": float(item.weight_step), "light_factor": float(item.light_factor),
        "heavy_factor": float(item.heavy_factor), "light_min": item.light_min,
        "light_max": item.light_max, "medium_min": item.medium_min,
        "medium_max": item.medium_max, "heavy_min": item.heavy_min,
        "heavy_max": item.heavy_max,
        "movement_id": item.movement_id, "rep_min": item.rep_min or item.medium_min,
        "rep_max": item.rep_max or item.medium_max,
        "rir_target": float(item.rir_target or 2),
        "duration_minutes": item.duration_minutes,
    }


def template_dict(item: WorkoutTemplate) -> dict:
    return {
        "id": item.id, "name": item.name, "muscle_group": item.muscle_group,
        "weekday": item.weekday, "send_time": item.send_time,
        "exercises": [exercise_dict(exercise) for exercise in item.exercises if exercise.active],
    }


def session_exercise_dict(item: SessionExercise) -> dict:
    step = float(item.exercise.weight_step)
    return {
        "id": item.id, "exercise_id": item.exercise_id, "name": item.name,
        "kind": item.kind, "target_duration_minutes": item.target_duration_minutes,
        "actual_duration_minutes": item.actual_duration_minutes,
        "position": item.position, "sets_count": item.sets_count,
        "weight_step": step,
        "target_weight": float(item.target_weight), "target_reps": item.target_reps,
        "min_reps": item.min_reps, "max_reps": item.max_reps,
        "skipped": item.skipped,
        "movement_id": item.movement_id, "primary_group": item.primary_group,
        "secondary_groups": split_details(item.secondary_groups), "is_anchor": item.is_anchor,
        "target_rir": float(item.target_rir) if item.target_rir is not None else None,
        "action_label": item.action_label, "next_set": next_set_suggestion(item, step),
        "results": [
            {"set_index": result.set_index, "weight": float(result.weight), "reps": result.reps,
             "rir_reported": float(result.rir_reported) if result.rir_reported is not None else None,
             "rir_target": float(result.rir_target) if result.rir_target is not None else None,
             "is_working": result.is_working,
             "is_hard_set": bool(result.is_working and result.rir_reported is not None and float(result.rir_reported) <= 3)}
            for result in item.results
        ],
    }


def session_dict(item: WorkoutSession, template: WorkoutTemplate) -> dict:
    return {
        "id": item.id, "template_id": item.template_id,
        "template_name": item.template_name, "muscle_group": item.muscle_group,
        "scheduled_date": item.scheduled_date.isoformat(), "actual_date": item.actual_date.isoformat() if item.actual_date else None,
        "phase": PHASES[item.phase] if item.phase_type is None else item.phase_type,
        "phase_type": item.phase_type,
        "week_id": item.week_id,
        "week_start": item.week.week_start.isoformat() if item.week else None,
        "week_number": item.week.week_number if item.week else None,
        "deload_reason": item.week.deload_reason if item.week else None,
        "feeling_beat_up": item.week.feeling_beat_up if item.week else False,
        "status": item.status,
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
        "exercises": [session_exercise_dict(exercise) for exercise in item.exercises],
    }
