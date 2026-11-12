"""A cycle advances only after every scheduled training slot is complete."""

import json
from datetime import date, datetime, timedelta, timezone

from app.analytics import progress_for_user
from app.models import Exercise, Movement, SetResult, User, WorkoutTemplate
from app.planning import due_cycle_slot, get_or_create_session, project_cycle
from app.muscles import ALL_DETAILED_GROUPS
from test_replacement_http import api_program, client, signed_header  # noqa: F401


def test_nine_day_cycle_waits_for_all_slots_and_deloads_after_three(database):
    with database() as db:
        user = User(telegram_id=700001, cycle_days=9, cycle_anchor=date(2026, 10, 26))
        db.add(user)
        db.flush()
        movement = Movement(user_id=user.telegram_id, name="Присед", primary_group="Приводящие мышцы")
        db.add(movement)
        db.flush()
        templates = []
        for number, days in enumerate(([1, 5], [3, 7], [9]), start=1):
            template = WorkoutTemplate(user_id=user.telegram_id, name=f"Тренировка {number}",
                                       muscle_group="Ноги", weekday=0, send_time="09:00",
                                       cycle_days_json=json.dumps(days))
            db.add(template)
            db.flush()
            db.add(Exercise(template_id=template.id, movement_id=movement.id, name="Присед",
                            medium_weight=40, weight_step=2.5, sets_count=2, rep_min=6, rep_max=10))
            templates.append(template)
        db.commit()

        assert "Приводящие мышцы" in ALL_DETAILED_GROUPS
        for cycle_index in range(4):
            start = date(2026, 10, 26) + timedelta(days=9 * cycle_index)
            phase = "deload" if cycle_index == 3 else "accumulation"
            for day, template_index in [(1, 0), (3, 1), (5, 0), (7, 1), (9, 2)]:
                due_date = start + timedelta(days=day - 1)
                due = due_cycle_slot(db, user, due_date)
                assert due is not None and due[0] == {"day": day, "template_id": templates[template_index].id}
                assert due[1] == due_date
                session = get_or_create_session(db, templates[template_index], due_date, day)
                assert session.phase_type == phase
                assert session.week.period_days == 9
                if day == 9 and cycle_index < 3:
                    assert project_cycle(db, user, start + timedelta(days=9)).week.week_start == start
                session.status = "completed"
                session.actual_date = due_date
                session.completed_at = datetime.combine(due_date, datetime.min.time(), timezone.utc)
                db.add(SetResult(session_exercise_id=session.exercises[0].id, set_index=1,
                                 weight=40, reps=8, rir_reported=2, is_working=True))
                db.commit()
            next_plan = project_cycle(db, user, start + timedelta(days=9))
            assert next_plan.week.week_start == start + timedelta(days=9)
            assert next_plan.week.phase_type == ("accumulation" if cycle_index == 3 else "deload" if cycle_index == 2 else "accumulation")
        progress = progress_for_user(db, user.telegram_id)
        assert [(row["week_start"], row["period_days"], row["working_sets"])
                for row in progress["weekly_summary"]] == [
            ((date(2026, 10, 26) + timedelta(days=9 * index)).isoformat(), 9, 5)
            for index in range(4)]
        assert [row["working_sets"] for row in progress["weeks"] if row["group"] == "Приводящие мышцы"] == [5] * 4
        assert progress["weeks"][0]["target_low"] == 15


def test_cycle_settings_and_override_are_owned(client, clock):
    headers, _, _ = api_program(client, clock, 730001)
    other = signed_header(730002, clock)
    template_id = client.get("/api/templates", headers=headers).json()[0]["id"]
    config = {"length_days": 9, "start_date": "2026-10-27",
              "slots": [{"day": 1, "template_id": template_id}, {"day": 5, "template_id": template_id}]}
    assert client.put("/api/program/cycle", headers=other, json=config).status_code == 422
    saved = client.put("/api/program/cycle", headers=headers, json=config)
    assert saved.status_code == 200, saved.text
    assert saved.json()["slots"] == config["slots"]
    assert client.get("/api/program/cycle", headers=headers).json()["length_days"] == 9
    assert client.get("/api/program/cycle", headers={**other, "X-Admin-Target-User-Id": "730001"}).status_code == 403
    override = client.put("/api/next-week", headers=headers, json={"kind": "deload"})
    assert override.status_code == 200 and override.json()["unit"] == "cycle"
    assert client.delete("/api/next-week", headers=headers).json()["kind"] is None
