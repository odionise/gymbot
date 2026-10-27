import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import Update
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from .analytics import progress_for_user
from .auth import current_user
from .bot import dispatcher, reminder_loop
from .config import get_settings
from .db import Base, engine, get_db
from .migrations import migrate
from .models import Exercise, Movement, MuscleTarget, SessionExercise, SetResult, TrainingWeek, User, WorkoutSession, WorkoutTemplate, utcnow
from .muscles import ALL_DETAILED_GROUPS, DETAILED_GROUPS
from .planning import get_or_create_session, movement_for, planned_counts, prescription, resolve_week
from .schemas import ExerciseIn, MovementIn, MuscleTargetIn, OverrideIn, RecoveryIn, RescheduleIn, ResultIn, SetsCountIn, SettingsIn, SkipIn, TemplateIn, VolumeCapIn
from .serializers import exercise_dict, movement_dict, session_dict, template_dict


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.app_env == "production" and (
        not settings.bot_token
        or settings.bot_token == "replace-with-botfather-token"
        or not settings.public_url.startswith("https://")
        or not settings.webhook_secret
        or settings.database_url.startswith("sqlite")
    ):
        raise RuntimeError("Production requires BOT_TOKEN, HTTPS PUBLIC_URL, WEBHOOK_SECRET and PostgreSQL")
    migrate(engine)
    bot = Bot(settings.bot_token) if settings.bot_token and settings.bot_token != "replace-with-botfather-token" else None
    app.state.bot = bot
    task = asyncio.create_task(reminder_loop(bot)) if bot else None
    if bot and settings.app_env == "production":
        await bot.set_webhook(
            f"{settings.public_url.rstrip('/')}/telegram/webhook",
            secret_token=settings.webhook_secret,
        )
    try:
        yield
    finally:
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        if bot:
            await bot.session.close()


app = FastAPI(title="Workout Mini App API", lifespan=lifespan)
if get_settings().app_env == "development":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"], allow_headers=["*"],
    )


def owned_template(db: Session, user: User, template_id: str) -> WorkoutTemplate:
    item = db.get(WorkoutTemplate, template_id)
    if not item or item.user_id != user.telegram_id or not item.active:
        raise HTTPException(404, "Workout not found")
    return item


def owned_exercise(db: Session, user: User, exercise_id: str) -> Exercise:
    item = db.get(Exercise, exercise_id)
    if not item or not item.active:
        raise HTTPException(404, "Exercise not found")
    owned_template(db, user, item.template_id)
    return item


def owned_movement(db: Session, user: User, movement_id: str) -> Movement:
    item = db.get(Movement, movement_id)
    if not item or item.user_id != user.telegram_id or not item.active:
        raise HTTPException(404, "Movement not found")
    return item


def owned_session(db: Session, user: User, session_id: str) -> WorkoutSession:
    item = db.get(WorkoutSession, session_id)
    if not item or item.user_id != user.telegram_id:
        raise HTTPException(404, "Session not found")
    return item


def owned_session_exercise(db: Session, user: User, item_id: str) -> tuple[WorkoutSession, SessionExercise]:
    item = db.get(SessionExercise, item_id)
    if not item:
        raise HTTPException(404, "Exercise not found")
    return owned_session(db, user, item.session_id), item


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/telegram/webhook")
async def telegram_webhook(
    update: dict,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    settings = get_settings()
    if not settings.webhook_secret or x_telegram_bot_api_secret_token != settings.webhook_secret:
        raise HTTPException(403)
    if app.state.bot is None:
        raise HTTPException(503)
    await dispatcher.feed_update(app.state.bot, Update.model_validate(update))
    return {"ok": True}


@app.get("/api/me")
def me(user: User = Depends(current_user)):
    return {"telegram_id": user.telegram_id, "timezone": user.timezone,
            "volume_cap": user.volume_cap, "has_started_bot": user.chat_id is not None}


@app.patch("/api/me")
def update_me(data: SettingsIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.timezone = data.timezone
    db.commit()
    return me(user)


@app.patch("/api/me/volume-cap")
def update_volume_cap(data: VolumeCapIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.volume_cap = data.volume_cap
    db.commit()
    return me(user)


@app.get("/api/muscle-groups")
def muscle_groups(user: User = Depends(current_user)):
    return DETAILED_GROUPS


@app.get("/api/muscle-targets")
def muscle_targets(user: User = Depends(current_user), db: Session = Depends(get_db)):
    saved = {item.muscle_group: item for item in db.scalars(select(MuscleTarget).where(
        MuscleTarget.user_id == user.telegram_id))}
    return {group: {"min_sets": saved[group].min_sets if group in saved else 12,
                    "max_sets": saved[group].max_sets if group in saved else 18,
                    "cap_sets": saved[group].cap_sets if group in saved else user.volume_cap}
            for group in ALL_DETAILED_GROUPS}


@app.put("/api/muscle-targets/{group}")
def update_muscle_target(group: str, data: MuscleTargetIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if group not in ALL_DETAILED_GROUPS:
        raise HTTPException(404, "Muscle group not found")
    item = db.scalar(select(MuscleTarget).where(MuscleTarget.user_id == user.telegram_id,
                                                MuscleTarget.muscle_group == group))
    if item is None:
        item = MuscleTarget(user_id=user.telegram_id, muscle_group=group)
        db.add(item)
    for key, value in data.model_dump().items():
        setattr(item, key, value)
    db.commit()
    return {"group": group, **data.model_dump()}


@app.get("/api/movements")
def movements(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [movement_dict(item) for item in db.scalars(select(Movement).where(
        Movement.user_id == user.telegram_id, Movement.active.is_(True)).order_by(Movement.name))]


@app.post("/api/movements")
def create_movement(data: MovementIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if data.is_anchor:
        for old in db.scalars(select(Movement).where(Movement.user_id == user.telegram_id,
                                                    Movement.primary_group == data.primary_group)):
            old.is_anchor = False
    item = Movement(user_id=user.telegram_id, name=data.name, primary_group=data.primary_group,
                    secondary_groups=", ".join(data.secondary_groups), is_anchor=data.is_anchor)
    db.add(item)
    db.commit()
    db.refresh(item)
    return movement_dict(item)


@app.put("/api/movements/{movement_id}")
def update_movement(movement_id: str, data: MovementIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = owned_movement(db, user, movement_id)
    if data.is_anchor:
        for old in db.scalars(select(Movement).where(Movement.user_id == user.telegram_id,
                                                    Movement.primary_group == data.primary_group,
                                                    Movement.id != movement_id)):
            old.is_anchor = False
    item.name, item.primary_group = data.name, data.primary_group
    item.secondary_groups, item.is_anchor = ", ".join(data.secondary_groups), data.is_anchor
    db.commit()
    return movement_dict(item)


@app.get("/api/templates")
def templates(user: User = Depends(current_user), db: Session = Depends(get_db)):
    items = db.scalars(select(WorkoutTemplate).where(
        WorkoutTemplate.user_id == user.telegram_id, WorkoutTemplate.active.is_(True)
    ).order_by(WorkoutTemplate.weekday, WorkoutTemplate.name)).all()
    return [template_dict(item) for item in items]


@app.post("/api/templates")
def create_template(data: TemplateIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = WorkoutTemplate(user_id=user.telegram_id, **data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return template_dict(item)


@app.put("/api/templates/{template_id}")
def update_template(template_id: str, data: TemplateIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = owned_template(db, user, template_id)
    for key, value in data.model_dump().items():
        setattr(item, key, value)
    db.commit()
    return template_dict(item)


@app.delete("/api/templates/{template_id}")
def delete_template(template_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = owned_template(db, user, template_id)
    item.active = False
    db.commit()
    return {"ok": True}


@app.post("/api/templates/{template_id}/exercises")
def create_exercise(template_id: str, data: ExerciseIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    owned_template(db, user, template_id)
    if not data.movement_id:
        raise HTTPException(422, "Choose a movement and its muscle groups")
    movement = owned_movement(db, user, data.movement_id)
    data.name = movement.name
    item = Exercise(template_id=template_id, **data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return exercise_dict(item)


@app.put("/api/exercises/{exercise_id}")
def update_exercise(exercise_id: str, data: ExerciseIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = owned_exercise(db, user, exercise_id)
    if data.movement_id:
        movement = owned_movement(db, user, data.movement_id)
        data.name = movement.name
    for key, value in data.model_dump().items():
        setattr(item, key, value)
    db.commit()
    return exercise_dict(item)


@app.delete("/api/exercises/{exercise_id}")
def delete_exercise(exercise_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = owned_exercise(db, user, exercise_id)
    item.active = False
    db.commit()
    return {"ok": True}


@app.get("/api/sessions/today")
def today_sessions(user: User = Depends(current_user), db: Session = Depends(get_db)):
    local_date = datetime.now(ZoneInfo(user.timezone)).date()
    due = db.scalars(select(WorkoutTemplate).where(
        WorkoutTemplate.user_id == user.telegram_id,
        WorkoutTemplate.active.is_(True),
        WorkoutTemplate.weekday == local_date.weekday(),
    )).all()
    for template in due:
        get_or_create_session(db, template, local_date)
    sessions = db.scalars(select(WorkoutSession).where(
        WorkoutSession.user_id == user.telegram_id,
        WorkoutSession.status != "completed",
    ).order_by(WorkoutSession.scheduled_date)).all()
    return [session_dict(item, db.get(WorkoutTemplate, item.template_id)) for item in sessions]


@app.post("/api/templates/{template_id}/start")
def start_session(template_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    template = owned_template(db, user, template_id)
    local_date = datetime.now(ZoneInfo(user.timezone)).date()
    session = get_or_create_session(db, template, local_date)
    if not session:
        raise HTTPException(400, "Add exercises first")
    if session.status == "completed":
        raise HTTPException(409, "This workout is already completed today")
    return session_dict(session, template)


@app.get("/api/sessions")
def history(user: User = Depends(current_user), db: Session = Depends(get_db)):
    items = db.scalars(select(WorkoutSession).where(
        WorkoutSession.user_id == user.telegram_id,
        WorkoutSession.status == "completed",
    ).order_by(WorkoutSession.completed_at.desc()).limit(100)).all()
    return [session_dict(item, db.get(WorkoutTemplate, item.template_id)) for item in items]


@app.get("/api/sessions/{session_id}")
def session_detail(session_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = owned_session(db, user, session_id)
    return session_dict(item, db.get(WorkoutTemplate, item.template_id))


@app.patch("/api/session-exercises/{item_id}/target")
def override_target(item_id: str, data: OverrideIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    session, item = owned_session_exercise(db, user, item_id)
    if session.status == "completed" or item.results:
        raise HTTPException(409, "Target can only change before recording sets")
    item.target_weight = data.target_weight
    item.target_reps = data.target_reps
    db.commit()
    return session_detail(session.id, user, db)


@app.patch("/api/session-exercises/{item_id}/skip")
def skip_exercise(item_id: str, data: SkipIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    session, item = owned_session_exercise(db, user, item_id)
    if session.status == "completed":
        raise HTTPException(409, "Session is completed")
    if data.skipped and item.results:
        raise HTTPException(409, "Delete recorded sets before skipping")
    item.skipped = data.skipped
    db.commit()
    return session_detail(session.id, user, db)


@app.patch("/api/session-exercises/{item_id}/sets-count")
def change_sets_count(item_id: str, data: SetsCountIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    session, item = owned_session_exercise(db, user, item_id)
    if session.status == "completed" or any(r.is_working and r.set_index > data.sets_count for r in item.results):
        raise HTTPException(409, "Cannot remove a recorded set")
    item.sets_count = data.sets_count
    db.commit()
    return session_detail(session.id, user, db)


@app.put("/api/session-exercises/{item_id}/sets/{set_index}")
def save_set(item_id: str, set_index: int, data: ResultIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    session, item = owned_session_exercise(db, user, item_id)
    if session.status == "completed" or item.skipped:
        raise HTTPException(409, "Exercise cannot be edited")
    if (data.is_working and (set_index < 1 or set_index > item.sets_count)) or (not data.is_working and (set_index > 0 or set_index < -5)):
        raise HTTPException(400, "Invalid set number")
    result = db.scalars(select(SetResult).where(
        SetResult.session_exercise_id == item.id, SetResult.set_index == set_index
    )).first()
    if result is None:
        result = SetResult(session_exercise_id=item.id, set_index=set_index)
        db.add(result)
    result.weight = data.weight
    result.reps = data.reps
    result.rir_reported = data.rir_reported
    result.rir_target = item.target_rir
    result.is_working = data.is_working
    session.status = "in_progress"
    db.commit()
    return session_detail(session.id, user, db)


@app.delete("/api/session-exercises/{item_id}/sets/{set_index}")
def remove_set(item_id: str, set_index: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    session, item = owned_session_exercise(db, user, item_id)
    if session.status == "completed":
        raise HTTPException(409, "Session is completed")
    result = db.scalars(select(SetResult).where(
        SetResult.session_exercise_id == item.id, SetResult.set_index == set_index
    )).first()
    if result:
        db.delete(result)
        db.commit()
    return session_detail(session.id, user, db)


@app.post("/api/sessions/{session_id}/complete")
def complete_session(session_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    session = owned_session(db, user, session_id)
    if session.status == "completed":
        return session_detail(session_id, user, db)
    if not session.exercises or all(item.skipped for item in session.exercises):
        raise HTTPException(400, "Record at least one exercise")
    if any(not item.skipped and len([r for r in item.results if r.is_working]) != item.sets_count for item in session.exercises):
        raise HTTPException(400, "Record all sets or skip the exercise")
    session.status = "completed"
    session.completed_at = utcnow()
    session.actual_date = datetime.now(ZoneInfo(user.timezone)).date()
    if session.phase_type is not None:
        actual_week = resolve_week(db, user.telegram_id, session.actual_date)
        session.week_id, session.phase_type = actual_week.id, actual_week.phase_type
    template = db.get(WorkoutTemplate, session.template_id)
    db.commit()
    return session_dict(session, template)


@app.patch("/api/sessions/{session_id}/reschedule")
def reschedule(session_id: str, data: RescheduleIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    session = owned_session(db, user, session_id)
    if session.status != "planned":
        raise HTTPException(409, "Only an unstarted session can be moved")
    try:
        new_date = date.fromisoformat(data.scheduled_date)
    except ValueError:
        raise HTTPException(422, "Invalid date")
    if new_date == session.scheduled_date:
        return session_dict(session, db.get(WorkoutTemplate, session.template_id))
    if db.scalar(select(WorkoutSession).where(WorkoutSession.template_id == session.template_id,
                                              WorkoutSession.scheduled_date == new_date)):
        raise HTTPException(409, "Workout already exists on that date")
    week = resolve_week(db, user.telegram_id, new_date)
    session.scheduled_date, session.week_id, session.phase_type = new_date, week.id, week.phase_type
    counts = planned_counts(db, user.telegram_id, week)
    prior = db.scalar(select(TrainingWeek).where(
        TrainingWeek.user_id == user.telegram_id, TrainingWeek.week_start < week.week_start
    ).order_by(TrainingWeek.week_start.desc()))
    reentry = bool(prior and prior.phase_type == "deload" and not prior.missed_deload)
    for item in session.exercises:
        exercise = db.get(Exercise, item.exercise_id)
        movement = movement_for(db, exercise, user.telegram_id)
        weight, reps, action = prescription(db, exercise, week, reentry)
        item.sets_count, item.target_weight, item.target_reps = counts[exercise.id], weight, reps
        item.target_rir, item.action_label = (2.5 if reentry else week.target_rir), action
        item.primary_group, item.secondary_groups = movement.primary_group, movement.secondary_groups
    db.commit()
    return session_dict(session, db.get(WorkoutTemplate, session.template_id))


@app.post("/api/weeks/{week_start}/manual-deload")
def manual_deload(week_start: date, user: User = Depends(current_user), db: Session = Depends(get_db)):
    week = resolve_week(db, user.telegram_id, week_start)
    if week.week_start != week_start or db.scalar(select(WorkoutSession).where(
        WorkoutSession.user_id == user.telegram_id, WorkoutSession.week_id == week.id)):
        raise HTTPException(409, "Choose a Monday before sessions are created")
    week.phase_type, week.deload_reason, week.target_rir = "deload", "manual", 4
    week.is_postponed = False
    db.commit()
    return {"week_start": week.week_start, "phase_type": week.phase_type, "reason": "manual"}


@app.patch("/api/weeks/{week_start}/recovery")
def update_recovery(week_start: date, data: RecoveryIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    week = resolve_week(db, user.telegram_id, week_start)
    if week.week_start != week_start:
        raise HTTPException(422, "Choose a Monday")
    week.feeling_beat_up = data.feeling_beat_up
    db.commit()
    return {"week_start": week_start, "feeling_beat_up": week.feeling_beat_up}


@app.get("/api/progress")
def progress(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return progress_for_user(db, user.telegram_id)
