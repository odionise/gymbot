from .models import Exercise, SessionExercise, WorkoutSession, WorkoutTemplate
from .planning import PHASES


def exercise_dict(item: Exercise) -> dict:
    return {
        "id": item.id, "name": item.name, "position": item.position,
        "sets_count": item.sets_count, "medium_weight": float(item.medium_weight),
        "weight_step": float(item.weight_step), "light_factor": float(item.light_factor),
        "heavy_factor": float(item.heavy_factor), "light_min": item.light_min,
        "light_max": item.light_max, "medium_min": item.medium_min,
        "medium_max": item.medium_max, "heavy_min": item.heavy_min,
        "heavy_max": item.heavy_max,
    }


def template_dict(item: WorkoutTemplate) -> dict:
    return {
        "id": item.id, "name": item.name, "muscle_group": item.muscle_group,
        "weekday": item.weekday, "send_time": item.send_time,
        "next_phase": PHASES[item.next_phase],
        "exercises": [exercise_dict(exercise) for exercise in item.exercises if exercise.active],
    }


def session_exercise_dict(item: SessionExercise) -> dict:
    return {
        "id": item.id, "exercise_id": item.exercise_id, "name": item.name,
        "position": item.position, "sets_count": item.sets_count,
        "target_weight": float(item.target_weight), "target_reps": item.target_reps,
        "min_reps": item.min_reps, "max_reps": item.max_reps,
        "skipped": item.skipped,
        "results": [
            {"set_index": result.set_index, "weight": float(result.weight), "reps": result.reps}
            for result in item.results
        ],
    }


def session_dict(item: WorkoutSession, template: WorkoutTemplate) -> dict:
    return {
        "id": item.id, "template_id": item.template_id,
        "template_name": item.template_name, "muscle_group": item.muscle_group,
        "scheduled_date": item.scheduled_date.isoformat(), "phase": PHASES[item.phase],
        "status": item.status,
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
        "exercises": [session_exercise_dict(exercise) for exercise in item.exercises],
    }
