"""Vercel request and schedule entrypoints must not start a second bot worker."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app import main
from app.db import make_engine


def test_marketplace_postgres_url_uses_installed_psycopg_driver():
    for prefix in ("postgres://", "postgresql://"):
        engine = make_engine(prefix + "user:pass@localhost/example")
        assert engine.dialect.name == "postgresql"
        assert engine.dialect.driver == "psycopg"
        engine.dispose()


def test_scheduled_reminders_require_secret_and_send_once(monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "synthetic-schedule-secret")
    sender = AsyncMock(return_value=2)
    monkeypatch.setattr(main, "send_due_reminders", sender)
    main.app.state.bot = object()
    with TestClient(main.app) as client:
        # Lifespan replaces app.state.bot when no BOT_TOKEN is configured.
        main.app.state.bot = object()
        assert client.post("/api/internal/reminders").status_code == 403
        assert client.post("/api/internal/reminders", headers={"Authorization": "Bearer wrong"}).status_code == 403
        response = client.post("/api/internal/reminders", headers={"Authorization": "Bearer synthetic-schedule-secret"})
    assert response.status_code == 200
    assert response.json() == {"sent": 2}
    sender.assert_awaited_once()


def test_vercel_lifespan_does_not_register_webhook_or_start_loop(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    settings = SimpleNamespace(app_env="production", bot_token="123456:synthetic-token",
                               public_url="https://gymbot.example", webhook_secret="synthetic-webhook-secret",
                               database_url="postgresql+psycopg://example", reminders_enabled=True)
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    monkeypatch.setattr(main, "migrate", lambda engine: None)
    bot = SimpleNamespace(set_webhook=AsyncMock(), session=SimpleNamespace(close=AsyncMock()))
    monkeypatch.setattr(main, "Bot", lambda token: bot)
    loop = AsyncMock()
    monkeypatch.setattr(main, "reminder_loop", loop)
    with TestClient(main.app) as client:
        assert client.get("/health").json() == {"ok": True}
    bot.set_webhook.assert_not_awaited()
    loop.assert_not_awaited()
    bot.session.close.assert_awaited_once()
