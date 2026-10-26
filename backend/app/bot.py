import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, MenuButtonWebApp, Message, WebAppInfo
from sqlalchemy import select

from .config import get_settings
from .db import SessionLocal
from .models import Reminder, User, WorkoutTemplate
from .planning import PHASES, get_or_create_session

logger = logging.getLogger(__name__)
router = Router()
dispatcher = Dispatcher()
dispatcher.include_router(router)


def app_button(session_id: str | None = None) -> InlineKeyboardMarkup:
    url = get_settings().public_url.rstrip("/")
    if session_id:
        url += f"/?session={session_id}"
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Открыть тренировку", web_app=WebAppInfo(url=url))
    ]])


@router.message(Command("start"))
async def start(message: Message, bot: Bot):
    if not message.from_user or not message.chat:
        return
    with SessionLocal() as db:
        user = db.get(User, message.from_user.id)
        if user is None:
            user = User(telegram_id=message.from_user.id)
            db.add(user)
        user.chat_id = message.chat.id
        db.commit()
    await bot.set_chat_menu_button(
        chat_id=message.chat.id,
        menu_button=MenuButtonWebApp(text="Тренировки", web_app=WebAppInfo(url=get_settings().public_url)),
    )
    await message.answer("Готово. Откройте приложение и настройте программу и расписание.", reply_markup=app_button())


@router.message(Command("today"))
async def today(message: Message):
    if not message.from_user:
        return
    with SessionLocal() as db:
        user = db.get(User, message.from_user.id)
        if not user:
            await message.answer("Сначала отправьте /start")
            return
        local_today = datetime.now(ZoneInfo(user.timezone)).date()
        templates = list(db.scalars(select(WorkoutTemplate).where(
            WorkoutTemplate.user_id == user.telegram_id,
            WorkoutTemplate.active.is_(True),
            WorkoutTemplate.weekday == local_today.weekday(),
        )))
        if not templates:
            await message.answer("На сегодня тренировок нет.", reply_markup=app_button())
            return
        for template in templates:
            session = get_or_create_session(db, template, local_today)
            if session:
                await message.answer(format_plan(session, local_today), reply_markup=app_button(session.id))


def format_plan(session, display_date) -> str:
    lines = [f"{session.template_name} · {PHASES[session.phase]} · {display_date:%d.%m.%Y}"]
    for exercise in session.exercises:
        lines.append(
            f"• {exercise.name}: {exercise.sets_count} × {exercise.target_reps} "
            f"по {float(exercise.target_weight):g} кг"
        )
    return "\n".join(lines)


async def send_due_reminders(bot: Bot, now: datetime | None = None) -> int:
    moment = now or datetime.now(timezone.utc)
    sent = 0
    with SessionLocal() as db:
        templates = list(db.scalars(select(WorkoutTemplate).where(WorkoutTemplate.active.is_(True))))
        for template in templates:
            user = db.get(User, template.user_id)
            if not user or not user.chat_id:
                continue
            local = moment.astimezone(ZoneInfo(user.timezone))
            if local.weekday() != template.weekday or local.strftime("%H:%M") < template.send_time:
                continue
            exists = db.scalars(select(Reminder).where(
                Reminder.template_id == template.id, Reminder.local_date == local.date()
            )).first()
            if exists:
                continue
            session = get_or_create_session(db, template, local.date())
            if not session or session.status == "completed":
                continue
            try:
                result = await bot.send_message(
                    user.chat_id, format_plan(session, local.date()), reply_markup=app_button(session.id)
                )
            except Exception:
                logger.exception("Could not send workout reminder for template %s", template.id)
                continue
            db.add(Reminder(template_id=template.id, local_date=local.date(), message_id=result.message_id))
            db.commit()
            sent += 1
    return sent


async def reminder_loop(bot: Bot):
    while True:
        try:
            await send_due_reminders(bot)
        except Exception:
            logger.exception("Reminder scan failed")
        await asyncio.sleep(60)
