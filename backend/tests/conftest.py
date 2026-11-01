"""Local-only settings and a controllable clock; no API lifespan or bot is started."""

import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
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


@pytest.fixture
def postgres_engine():
    """One owned schema on an explicitly configured, disposable local server."""
    raw_url = os.environ.get("GYMBOT_TEST_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set GYMBOT_TEST_POSTGRES_URL for a disposable loopback gymbot_test database")
    url = make_url(raw_url)
    if (url.get_backend_name() != "postgresql" or url.host not in ("127.0.0.1", "localhost")
            or url.database != "gymbot_test"):
        pytest.fail("PostgreSQL checks accept only a loopback database named gymbot_test", pytrace=False)
    schema = "gymbot_stage1_" + uuid4().hex
    admin = create_engine(url)
    try:
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
        try:
            yield engine
        finally:
            engine.dispose()
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    finally:
        admin.dispose()


@pytest.fixture
def postgres_database(postgres_engine):
    from app.migrations import migrate

    migrate(postgres_engine)
    return sessionmaker(bind=postgres_engine, expire_on_commit=False)
