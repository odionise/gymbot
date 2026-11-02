"""Saved calculation inputs are historical evidence, not a live recomputation."""

import json

from .models import SessionExercise


def recommendation_dict(item: SessionExercise) -> dict | None:
    if item.recommendation_context_json is None:
        return None
    try:
        value = json.loads(item.recommendation_context_json)
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def save_recommendation(item: SessionExercise, value: dict) -> None:
    item.recommendation_context_json = json.dumps(value, ensure_ascii=False, allow_nan=False)


def record_manual_target(item: SessionExercise, **values: float | int) -> None:
    context = recommendation_dict(item)
    if context is None:
        # A manual edit is known; the original calculation of a legacy plan is
        # not. Preserve that distinction instead of inventing an automatic plan.
        context = {"version": 1, "rules_version": None, "calculated": None, "manual_override": {}}
    context["manual_override"] = {**context.get("manual_override", {}), **values}
    save_recommendation(item, context)
