from collections import defaultdict
from datetime import datetime, timedelta
import json
from statistics import mean, median
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import TrainingWeek, User, WorkoutSession
from .muscles import split_details, split_muscle_groups
from .planning import PHASES, monday


def progress_for_user(db: Session, user_id: int) -> dict:
    user = db.get(User, user_id)
    local_today = datetime.now(ZoneInfo(user.timezone)).date()
    sessions = list(db.scalars(select(WorkoutSession).where(
        WorkoutSession.user_id == user_id, WorkoutSession.status == "completed"
    ).order_by(WorkoutSession.completed_at)))
    exercise_points = defaultdict(list)
    weekly = defaultdict(lambda: {"hard_sets": 0.0, "working_sets": 0.0,
                                   "tonnage": 0.0, "rirs": [], "reps": defaultdict(list)})
    for session in sessions:
        day = session.actual_date or session.scheduled_date
        start = monday(day)
        for exercise in session.exercises:
            if exercise.kind != "strength" or exercise.skipped or not exercise.results:
                continue
            results = [r for r in exercise.results if r.is_working]
            if not results:
                continue
            groups = ([exercise.primary_group] + split_details(exercise.secondary_groups)
                      if exercise.primary_group and exercise.primary_group != "Не назначено"
                      else split_muscle_groups(session.muscle_group))
            phase = session.phase_type or PHASES[session.phase]
            volume = sum(float(r.weight) * r.reps for r in results)
            strength = max((float(r.weight) * (1 + r.reps / 30)
                            for r in results if 2 <= r.reps <= 10), default=None)
            exercise_points[exercise.exercise_id].append({
                "name": exercise.name, "group": groups[0] if groups else "",
                "groups": groups, "date": day.isoformat(), "phase": phase,
                "weight": max(float(r.weight) for r in results),
                "reps": max(r.reps for r in results), "volume": round(volume, 2),
                "estimated_strength": round(strength, 2) if strength is not None else None,
            })
            if session.phase_type is None or exercise.primary_group == "Не назначено":
                continue
            factors = [(exercise.primary_group, 1.0)] + [(g, 0.5) for g in split_details(exercise.secondary_groups)]
            for group, factor in factors:
                bucket = weekly[(start, group)]
                for r in results:
                    bucket["working_sets"] += factor
                    bucket["tonnage"] += float(r.weight) * r.reps * factor
                    if r.rir_reported is not None:
                        bucket["rirs"].append(float(r.rir_reported))
                        if float(r.rir_reported) <= 3:
                            bucket["hard_sets"] += factor
                            if session.phase_type == "accumulation":
                                bucket["reps"][(exercise.exercise_id, float(r.weight), float(r.rir_reported))].append(r.reps)
    weeks = {w.week_start: w for w in db.scalars(select(TrainingWeek).where(
        TrainingWeek.user_id == user_id).order_by(TrainingWeek.week_start))}
    comparable = defaultdict(set)
    for (start, group), bucket in weekly.items():
        if weeks.get(start) and weeks[start].phase_type == "accumulation":
            for key in bucket["reps"]:
                comparable[(group, key)].add(start)
    rows = []
    signals = []
    for (start, group), data in sorted(weekly.items()):
        week = weeks.get(start)
        phase = week.phase_type if week else "accumulation"
        custom = json.loads(week.targets_json or "{}").get(group, [12, 18, 20]) if week else [12, 18, 20]
        target_low = min(custom[1], custom[0] + 2 * max(0, (week.week_number if week else 1) - 1))
        target_high = min(custom[1], target_low + 2)
        quality = [mean(values) for key, values in data["reps"].items()
                   if phase == "accumulation" and len(comparable[(group, key)]) >= 2]
        row = {"week_start": start.isoformat(), "group": group, "phase": phase,
               "deload_reason": week.deload_reason if week else None,
               "hard_sets": round(data["hard_sets"], 1),
               "working_sets": round(data["working_sets"], 1),
               "tonnage": round(data["tonnage"], 1),
               "avg_rir": round(mean(data["rirs"]), 1) if data["rirs"] else None,
               "avg_reps_hard": round(mean(quality), 1) if quality else None,
               "target_low": 5 if phase == "deload" else target_low,
               "target_high": 8 if phase == "deload" else target_high}
        if phase == "deload":
            prior = [r for r in rows if r["group"] == group and r["phase"] == "accumulation"]
            baseline = median(r["working_sets"] for r in prior[-2:]) if prior else None
            row["missed_deload"] = bool(baseline and row["working_sets"] >= 0.8 * baseline)
            if row["missed_deload"]:
                row["phase"] = "missed_deload"
                signals.append(f"{group}: Легкая неделя не снизила объём")
            if row["working_sets"] < 5 and start + timedelta(days=6) < local_today:
                signals.append(f"{group}: в легкую неделю менее 5 рабочих подходов")
        else:
            row["missed_deload"] = False
            if row["hard_sets"] < 10 and start + timedelta(days=6) < local_today:
                signals.append(f"{group}: менее 10 жёстких подходов за неделю")
            if row["hard_sets"] > 20:
                signals.append(f"{group}: объём превысил 20 жёстких подходов")
            if row["avg_rir"] is not None and row["avg_rir"] < 1:
                signals.append(f"{group}: средний ПДО ниже 1 — проверьте восстановление")
        if week and week.feeling_beat_up:
            signals.append(f"{group}: отмечено тяжело/болит; рост объёма приостановлен")
        rows.append(row)
    return {
        "exercises": [{"id": key, "name": points[-1]["name"], "group": points[-1]["group"],
                       "groups": list(dict.fromkeys(g for p in points for g in p["groups"])),
                       "points": points} for key, points in exercise_points.items()],
        "weeks": rows, "signals": signals,
        "groups": [{"group": group, "cycle_volume": round(sum(r["tonnage"] for r in rows if r["group"] == group and r["phase"] == "accumulation"), 1),
                    "strength_change_percent": None,
                    "sessions": sum(1 for s in sessions if group in split_muscle_groups(s.muscle_group))}
                   for group in sorted({r["group"] for r in rows})],
    }
