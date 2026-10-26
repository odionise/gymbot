from collections import defaultdict
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import WorkoutSession
from .muscles import split_muscle_groups
from .planning import PHASES


def progress_for_user(db: Session, user_id: int) -> dict:
    sessions = list(db.scalars(select(WorkoutSession).where(
        WorkoutSession.user_id == user_id,
        WorkoutSession.status == "completed",
    ).order_by(WorkoutSession.completed_at)))
    exercise_points = defaultdict(list)
    group_cycles = defaultdict(list)
    for session in sessions:
        session_groups = split_muscle_groups(session.muscle_group)
        group_volume = 0.0
        for exercise in session.exercises:
            if exercise.skipped or not exercise.results:
                continue
            volume = sum(float(item.weight) * item.reps for item in exercise.results)
            group_volume += volume
            best_strength = max(
                (float(item.weight) * (1 + item.reps / 30) for item in exercise.results if 2 <= item.reps <= 10),
                default=None,
            )
            exercise_points[exercise.exercise_id].append({
                "name": exercise.name,
                "group": session_groups[0] if session_groups else session.muscle_group,
                "groups": session_groups,
                "date": session.scheduled_date.isoformat(),
                "phase": PHASES[session.phase],
                "weight": max(float(item.weight) for item in exercise.results),
                "reps": max(item.reps for item in exercise.results),
                "volume": round(volume, 2),
                "estimated_strength": round(best_strength, 2) if best_strength is not None else None,
            })
        for group in session_groups:
            group_cycles[group].append({
                "date": session.scheduled_date.isoformat(),
                "phase": PHASES[session.phase],
                "volume": round(group_volume, 2),
            })
    summaries = []
    for group, workouts in group_cycles.items():
        exercise_changes = []
        for points in exercise_points.values():
            group_points = [point for point in points if group in point["groups"]]
            if not group_points:
                continue
            phase_changes = []
            for phase in PHASES:
                values = [
                    point["estimated_strength"] for point in group_points
                    if point["phase"] == phase and point["estimated_strength"]
                ]
                if len(values) >= 2 and values[0] > 0:
                    phase_changes.append((values[-1] / values[0] - 1) * 100)
            if phase_changes:
                exercise_changes.append(mean(phase_changes))
        summaries.append({
            "group": group,
            "cycle_volume": round(sum(item["volume"] for item in workouts[-3:]), 2),
            "strength_change_percent": round(mean(exercise_changes), 1) if exercise_changes else None,
            "sessions": len(workouts),
        })
    return {
        "exercises": [
            {
                "id": exercise_id, "name": points[-1]["name"],
                "group": points[-1]["group"],
                "groups": list(dict.fromkeys(group for point in points for group in point["groups"])),
                "points": points,
            }
            for exercise_id, points in exercise_points.items()
        ],
        "groups": summaries,
    }
