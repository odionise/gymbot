"""No real Telegram calls: plans and reminder destinations stay private."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select, update

from app import bot
from app.main import me
from app.models import User, WorkoutSession
from test_history import program


@pytest.mark.parametrize("kind", ["group", "supergroup", "channel"])
def test_group_commands_do_not_change_private_chat_or_disclose_plan(database, monkeypatch, kind):
    with database() as db:
        user, _, _ = program(db)
        user.chat_id = user.telegram_id
        db.commit()
    monkeypatch.setattr(bot, "SessionLocal", database)
    message = SimpleNamespace(from_user=SimpleNamespace(id=1001),
                              chat=SimpleNamespace(id=-42, type=kind), answer=AsyncMock())
    telegram = SimpleNamespace(set_chat_menu_button=AsyncMock())
    asyncio.run(bot.start(message, telegram))
    asyncio.run(bot.today(message))
    message.answer.assert_not_awaited()
    telegram.set_chat_menu_button.assert_not_awaited()
    with database() as db:
        assert db.get(User, 1001).chat_id == 1001
        assert db.scalar(select(func.count()).select_from(WorkoutSession)) == 0


@pytest.mark.parametrize("chat_id", [-42, 2002, None])
def test_reminders_do_not_use_legacy_group_or_foreign_destinations(database, monkeypatch, clock, chat_id):
    with database() as db:
        user, _, _ = program(db)
        user.chat_id = chat_id
        db.commit()
        assert me(user)["has_started_bot"] is False
    monkeypatch.setattr(bot, "SessionLocal", database)
    telegram = SimpleNamespace(send_message=AsyncMock())
    assert asyncio.run(bot.send_due_reminders(telegram, clock.moment)) == 0
    telegram.send_message.assert_not_awaited()
    with database() as db:
        assert db.get(User, 1001).chat_id == chat_id  # Preserve the original data.
        assert db.scalar(select(func.count()).select_from(WorkoutSession)) == 0


def test_private_start_and_one_reminder_still_work(database, monkeypatch, clock):
    with database() as db:
        program(db)
    monkeypatch.setattr(bot, "SessionLocal", database)
    monkeypatch.setattr(bot, "get_settings", lambda: SimpleNamespace(public_url="https://synthetic.invalid"))
    message = SimpleNamespace(from_user=SimpleNamespace(id=1001),
                              chat=SimpleNamespace(id=1001, type="private"), answer=AsyncMock())
    telegram = SimpleNamespace(set_chat_menu_button=AsyncMock(),
                               send_message=AsyncMock(return_value=SimpleNamespace(message_id=1)))
    asyncio.run(bot.start(message, telegram))
    assert asyncio.run(bot.send_due_reminders(telegram, clock.moment)) == 1
    assert asyncio.run(bot.send_due_reminders(telegram, clock.moment)) == 0
    telegram.send_message.assert_awaited_once()
    assert telegram.send_message.call_args.args[0] == 1001
    with database() as db:
        assert me(db.get(User, 1001))["has_started_bot"] is True


def test_telegram_wait_does_not_hold_database_write_locks(database, monkeypatch, clock):
    from app.planning import get_or_create_session
    from test_history import START
    with database() as db:
        user, template, _ = program(db)
        user.chat_id = user.telegram_id
        db.commit()
        get_or_create_session(db, template, START)  # Exercise the existing-plan path.
    monkeypatch.setattr(bot, "SessionLocal", database)
    monkeypatch.setattr(bot, "get_settings", lambda: SimpleNamespace(public_url="https://synthetic.invalid"))

    async def telegram_wait(*args, **kwargs):
        # A second request must be able to write while Telegram is awaiting I/O.
        with database() as db:
            db.execute(update(User).where(User.telegram_id == 1001).values(volume_cap=21))
            db.commit()
        return SimpleNamespace(message_id=1)

    telegram = SimpleNamespace(send_message=AsyncMock(side_effect=telegram_wait))
    assert asyncio.run(bot.send_due_reminders(telegram, clock.moment)) == 1
    message = SimpleNamespace(from_user=SimpleNamespace(id=1001),
                              chat=SimpleNamespace(id=1001, type="private"),
                              answer=AsyncMock(side_effect=telegram_wait))
    asyncio.run(bot.today(message))
    message.answer.assert_awaited_once()
