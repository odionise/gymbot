import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
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
from .models import Exercise, SessionExercise, SetResult, User, WorkoutSession, WorkoutTemplate, utcnow
from .planning import get_or_create_session
from .schemas import ExerciseIn, OverrideIn, ResultIn, SettingsIn, SkipIn, TemplateIn
from .serializers import exercise_dict, session_dict, template_dict


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
    Base.metadata.create_all(engine)
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
    return {"telegram_id": user.telegram_id, "timezone": user.timezone, "has_started_bot": user.chat_id is not None}


@app.patch("/api/me")
def update_me(data: SettingsIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.timezone = data.timezone
    db.commit()
    return me(user)


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
    item = Exercise(template_id=template_id, **data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return exercise_dict(item)


@app.put("/api/exercises/{exercise_id}")
def update_exercise(exercise_id: str, data: ExerciseIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = owned_exercise(db, user, exercise_id)
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


@app.put("/api/session-exercises/{item_id}/sets/{set_index}")
def save_set(item_id: str, set_index: int, data: ResultIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    session, item = owned_session_exercise(db, user, item_id)
    if session.status == "completed" or item.skipped:
        raise HTTPException(409, "Exercise cannot be edited")
    if set_index < 1 or set_index > item.sets_count:
        raise HTTPException(400, "Invalid set number")
    result = db.scalars(select(SetResult).where(
        SetResult.session_exercise_id == item.id, SetResult.set_index == set_index
    )).first()
    if result is None:
        result = SetResult(session_exercise_id=item.id, set_index=set_index)
        db.add(result)
    result.weight = data.weight
    result.reps = data.reps
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
    if any(not item.skipped and len(item.results) != item.sets_count for item in session.exercises):
        raise HTTPException(400, "Record all sets or skip the exercise")
    session.status = "completed"
    session.completed_at = utcnow()
    template = db.get(WorkoutTemplate, session.template_id)
    template.next_phase = (session.phase + 1) % 3
    db.commit()
    return session_dict(session, template)


@app.get("/api/progress")
def progress(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return progress_for_user(db, user.telegram_id)
