import asyncio
import logging
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, MenuButtonWebApp, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove, WebAppInfo
from sqlalchemy import select

from .config import get_settings
from .db import SessionLocal
from .models import Reminder, User, WeekOverride, WorkoutTemplate
from .planning import PHASES, due_cycle_slot, get_or_create_session, monday

logger = logging.getLogger(__name__)
router = Router()
dispatcher = Dispatcher()
dispatcher.include_router(router)


def profile_complete(user: User) -> bool:
    return bool(user.sex and user.display_name and user.birth_date)


def profile_prompt(user: User, suggested_name: str | None = None):
    if not user.sex:
        return ("Перед первой тренировкой заполните анкету. Выберите пол для схемы мышц:",
                ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Мужской"), KeyboardButton(text="Женский")]],
                                    resize_keyboard=True, one_time_keyboard=True))
    if not user.display_name:
        suggestion = f" Можно ответить «{suggested_name}»." if suggested_name else ""
        return (f"Как вас зовут?{suggestion}", ReplyKeyboardRemove())
    return ("Укажите дату рождения в формате ДД.ММ.ГГГГ. Возраст будет обновляться автоматически.", ReplyKeyboardRemove())


def app_button(session_id: str | None = None) -> InlineKeyboardMarkup:
    url = get_settings().public_url.rstrip("/")
    if session_id:
        url += f"/?session={session_id}"
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Открыть тренировку", web_app=WebAppInfo(url=url))
    ]])


@router.message(Command("start"))
async def start(message: Message, bot: Bot):
    if not message.from_user or not message.chat or message.chat.type != "private":
        return
    with SessionLocal() as db:
        user = db.get(User, message.from_user.id)
        if user is None:
            user = User(telegram_id=message.from_user.id)
            db.add(user)
        user.chat_id = message.chat.id
        user.telegram_username = getattr(message.from_user, "username", None)
        db.commit()
        prompt = profile_prompt(user, getattr(message.from_user, "first_name", None)) if not profile_complete(user) else None
    await bot.set_chat_menu_button(
        chat_id=message.chat.id,
        menu_button=MenuButtonWebApp(text="Тренировки", web_app=WebAppInfo(url=get_settings().public_url)),
    )
    if prompt:
        await message.answer(prompt[0], reply_markup=prompt[1])
    else:
        await message.answer("Готово. Откройте приложение и настройте программу и расписание.", reply_markup=app_button())


async def profile_answer(message: Message):
    if not message.from_user or not message.chat or message.chat.type != "private":
        return
    with SessionLocal() as db:
        user = db.get(User, message.from_user.id)
        if not user or profile_complete(user):
            return
        value = (message.text or "").strip()
        error = None
        if not user.sex:
            user.sex = {"Мужской": "male", "Женский": "female"}.get(value)
            if not user.sex:
                error = "Выберите «Мужской» или «Женский» кнопкой ниже."
        elif not user.display_name:
            if not value or len(value) > 80 or value.startswith("/"):
                error = "Укажите имя длиной до 80 символов."
            else:
                user.display_name = value
        else:
            try:
                parsed = date.fromisoformat(value) if "-" in value else datetime.strptime(value, "%d.%m.%Y").date()
                today = datetime.now(ZoneInfo(user.timezone)).date()
                if parsed >= today or parsed.year < 1900:
                    raise ValueError("Invalid birth date")
                user.birth_date = parsed
            except ValueError:
                error = "Укажите прошедшую дату рождения: ДД.ММ.ГГГГ."
        db.commit()
        complete = profile_complete(user)
        prompt = profile_prompt(user, getattr(message.from_user, "first_name", None)) if not complete else None
    if error:
        await message.answer(error, reply_markup=prompt[1] if prompt else ReplyKeyboardRemove())
    elif complete:
        await message.answer("Анкета заполнена. Откройте приложение и настройте программу.", reply_markup=app_button())
    else:
        await message.answer(prompt[0], reply_markup=prompt[1])


@router.message(Command("today"))
async def today(message: Message):
    if not message.from_user or not message.chat or message.chat.type != "private":
        return
    with SessionLocal() as db:
        replies = today_replies(db, message.from_user.id)
    # Snapshot text/keyboards first, close the transaction, then await Telegram.
    for text, keyboard in replies:
        await message.answer(text, reply_markup=keyboard)


def today_replies(db, user_id):
    user = db.get(User, user_id)
    if not user:
        return [("Сначала отправьте /start", None)]
    if not profile_complete(user):
        return [profile_prompt(user)]
    local_today = datetime.now(ZoneInfo(user.timezone)).date()
    cycle_due = due_cycle_slot(db, user, local_today) if user.cycle_days is not None else None
    templates = ([db.get(WorkoutTemplate, cycle_due[0]["template_id"])] if cycle_due else []) if user.cycle_days is not None else list(db.scalars(select(WorkoutTemplate).where(
        WorkoutTemplate.user_id == user.telegram_id, WorkoutTemplate.active.is_(True),
        WorkoutTemplate.weekday == local_today.weekday(),
    )))
    if not templates:
        return [("На сегодня тренировок нет.", app_button())]
    replies = []
    for template in templates:
        if template is None or not template.active:
            continue
        session = get_or_create_session(db, template, cycle_due[1], cycle_due[0]["day"]) if cycle_due else get_or_create_session(db, template, local_today)
        if session:
            replies.append((format_plan(session, local_today), app_button(session.id)))
    if replies:
        return replies
    vacation = db.scalar(select(WeekOverride).where(
        WeekOverride.user_id == user.telegram_id, WeekOverride.week_start == monday(local_today),
        WeekOverride.kind == "vacation"))
    text = ("На этой неделе отпуск. Тренировки продолжатся после него." if vacation else
            "В плане пока нет упражнений. Добавьте их в Mini App.")
    return [(text, app_button())]


def format_plan(session, display_date) -> str:
    cycle = bool(session.week and session.week.period_kind == "cycle")
    phase = ("Лёгкий цикл" if cycle else "Легкая неделя") if session.phase_type == "deload" else "накопление" if session.phase_type else PHASES[session.phase]
    lines = [f"{session.template_name} · {phase} · {display_date:%d.%m.%Y}"]
    if session.week and session.week.deload_reason:
        reason = {"scheduled": "после трёх завершённых циклов" if cycle else "по календарю",
                  "auto": "по сигналам восстановления", "manual": "по вашему выбору"}[session.week.deload_reason]
        lines.append(f"{'Лёгкий цикл' if cycle else 'Легкая неделя'} {reason}")
    for exercise in session.exercises:
        if exercise.kind != "strength":
            lines.append(f"• {exercise.name}: {exercise.target_duration_minutes} мин")
            continue
        lines.append(
            f"• {exercise.name}: {exercise.sets_count} × {exercise.target_reps} "
            f"по {float(exercise.target_weight):g} кг"
            + (f" · ПДО {float(exercise.target_rir):g}" if exercise.target_rir is not None else "")
        )
        if exercise.action_label:
            lines.append(f"  {exercise.action_label}")
    return "\n".join(lines)


async def send_due_reminders(bot: Bot, now: datetime | None = None) -> int:
    moment = now or datetime.now(timezone.utc)
    sent = 0
    with SessionLocal() as db:
        templates = list(db.scalars(select(WorkoutTemplate).where(WorkoutTemplate.active.is_(True))))
        for template in templates:
            user = db.get(User, template.user_id)
            # Retained group/foreign chat IDs must never receive a personal plan.
            # /start in a private chat can repair the link without rewriting data.
            if not user or user.chat_id != user.telegram_id or not profile_complete(user):
                continue
            local = moment.astimezone(ZoneInfo(user.timezone))
            cycle_due = due_cycle_slot(db, user, local.date()) if user.cycle_days is not None else None
            if user.cycle_days is not None:
                if not cycle_due or cycle_due[0]["template_id"] != template.id:
                    continue
            elif local.weekday() != template.weekday:
                continue
            if local.strftime("%H:%M") < template.send_time:
                continue
            exists = db.scalars(select(Reminder).where(
                Reminder.template_id == template.id, Reminder.local_date == local.date()
            )).first()
            if exists:
                continue
            session = (get_or_create_session(db, template, cycle_due[1], cycle_due[0]["day"])
                       if cycle_due else get_or_create_session(db, template, local.date()))
            if not session or session.status == "completed":
                db.rollback()
                continue
            chat_id, template_id = user.chat_id, template.id
            text, keyboard = format_plan(session, local.date()), app_button(session.id)
            db.rollback()  # Never hold a user's write lock during a network call.
            try:
                result = await bot.send_message(
                    chat_id, text, reply_markup=keyboard
                )
            except Exception:
                logger.exception("Could not send workout reminder for template %s", template_id)
                continue
            db.add(Reminder(template_id=template_id, local_date=local.date(), message_id=result.message_id))
            db.commit()
            sent += 1
    return sent


router.message.register(profile_answer)


async def reminder_loop(bot: Bot):
    while True:
        try:
            await send_due_reminders(bot)
        except Exception:
            logger.exception("Reminder scan failed")
        await asyncio.sleep(60)
