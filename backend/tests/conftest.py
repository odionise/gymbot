"""Local-only settings and a controllable clock; no API lifespan or bot is started."""

import os
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import sessionmaker

# Set these before test modules import app.main / app.db. A local .env or inherited
# production variables must not select the application database or a Telegram bot.
os.environ.update(
    APP_ENV="development",
    DATABASE_URL="sqlite:///:memory:",
    BOT_TOKEN="",
    WEBHOOK_SECRET="",
    DEV_TELEGRAM_ID="0",
    PUBLIC_URL="http://127.0.0.1",
)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    from app import analytics, bot, main, models

    class Clock:
        moment = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)

        def set(self, moment):
            if moment.tzinfo is None:
                raise ValueError("Test time must include a timezone")
            self.moment = moment.astimezone(timezone.utc)

    controlled = Clock()

    class ControlledDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return controlled.moment.replace(tzinfo=None)
            return controlled.moment.astimezone(tz)

    for module in (analytics, bot, main, models):
        monkeypatch.setattr(module, "datetime", ControlledDateTime)
    return controlled


@pytest.fixture
def database(tmp_path):
    from app.db import make_engine
    from app.migrations import migrate

    engine = make_engine("sqlite:///" + str(tmp_path / "test.db"))
    migrate(engine)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False)
    finally:
        engine.dispose()
