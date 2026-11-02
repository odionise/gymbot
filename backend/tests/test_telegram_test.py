"""Test-launcher isolation and bot side-effect guards, with synthetic secrets.

No Telegram requests, tunnel, application server or database service is started
by these tests. The real lifespan is exercised with a fake bot and migration.
"""

import asyncio
import importlib
import io
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from sqlalchemy.engine import make_url

from app import config, main


TOKEN = "1234567890:" + "A" * 35
USERNAME = "synthetic_gymbot_test_bot"


@pytest.fixture
def launcher(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    return importlib.import_module("telegram_test")


@pytest.fixture
def stand_config():
    return {"version": 1, "workspace": str(Path(__file__).resolve().parents[2]),
            "instance_id": "a" * 32, "pg_port": 55444, "http_port": 58081,
            "db_name": "gymbot_telegram", "db_user": "gymbot_tg_test",
            "db_password": "b" * 48, "webhook_secret": "c" * 64}


class FakeTelegram:
    def __init__(self, *, username=USERNAME, bot_id=111111, hook=""):
        self.identity = SimpleNamespace(username=username, id=bot_id)
        self.hook = hook
        self.writes = []

    async def get_me(self):
        return self.identity

    async def get_webhook_info(self):
        return SimpleNamespace(url=self.hook)

    async def set_webhook(self, url, **kwargs):
        self.writes.append(("set", url, kwargs))
        self.hook = url
        return True

    async def delete_webhook(self, **kwargs):
        self.writes.append(("delete", kwargs))
        self.hook = ""
        return True


def test_bot_file_loads_only_its_two_fields_without_shell_evaluation(launcher, tmp_path):
    path = tmp_path / "bot.env"
    # Notepad can save a UTF-8 BOM; both ordinary username forms are harmless.
    path.write_text(f"# Synthetic file\nTEST_BOT_USERNAME=@{USERNAME}\nTEST_BOT_TOKEN={TOKEN}\n", encoding="utf-8-sig")
    assert launcher.load_bot_config(path) == {"username": USERNAME, "token": TOKEN}


@pytest.mark.parametrize("text", [
    "TEST_BOT_USERNAME=\nTEST_BOT_TOKEN=\n",
    f"TEST_BOT_USERNAME=main_bot\nTEST_BOT_TOKEN={TOKEN}\n",
    f"TEST_BOT_USERNAME={USERNAME}\nTEST_BOT_TOKEN=invalid-token\n",
    f"TEST_BOT_USERNAME={USERNAME}\nTEST_BOT_TOKEN={TOKEN}\nBOT_TOKEN=primary\n",
    f"TEST_BOT_USERNAME={USERNAME}\nTEST_BOT_TOKEN={TOKEN}\nTEST_BOT_TOKEN={TOKEN}\n",
    f"TEST_BOT_USERNAME={USERNAME}\nTEST_BOT_TOKEN=$(forbidden-command)\n",
])
def test_invalid_bot_file_is_rejected_locally(launcher, tmp_path, text):
    path = tmp_path / "bot.env"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(launcher.TestStandError):
        launcher.load_bot_config(path)


@pytest.mark.parametrize("offline", [False, True])
def test_stand_settings_ignore_inherited_main_environment(launcher, stand_config, monkeypatch, offline):
    inherited = dict(APP_ENV="production", BOT_TOKEN="fake-main-token",
                     DATABASE_URL="postgresql://primary:fake-password@primary.invalid/main",
                     PUBLIC_URL="https://primary.invalid", WEBHOOK_SECRET="fake-main-secret",
                     DEV_TELEGRAM_ID="999999", REMINDERS_ENABLED="true")
    for key, value in inherited.items():
        monkeypatch.setenv(key, value)
    settings = launcher.build_settings(stand_config, TOKEN, "https://synthetic.trycloudflare.com", offline=offline)
    url = make_url(settings.database_url)
    assert (url.host, url.port, url.database, url.username, url.password) == (
        "127.0.0.1", stand_config["pg_port"], "gymbot_telegram", "gymbot_tg_test", stand_config["db_password"],
    )
    assert settings.app_env == "development"
    assert settings.bot_token == ("" if offline else TOKEN)
    assert settings.public_url == ("http://127.0.0.1:58081" if offline else "https://synthetic.trycloudflare.com")
    assert settings.webhook_secret == stand_config["webhook_secret"]
    assert settings.dev_telegram_id == 0
    assert settings.reminders_enabled is False


@pytest.mark.parametrize("url", ["http://localhost:58081", "https://primary.invalid",
                                  "https://synthetic.trycloudflare.com.evil.invalid",
                                  "https://synthetic.trycloudflare.com/unexpected-path"])
def test_online_profile_refuses_a_non_test_tunnel_address(launcher, stand_config, url):
    with pytest.raises(launcher.TestStandError):
        launcher.build_settings(stand_config, TOKEN, url)


def test_formatter_removes_raw_and_encoded_secrets_from_message_and_traceback(launcher):
    password = "test-only-password+%/"
    formatter = launcher.RedactingFormatter((TOKEN, password, "test-only-webhook-secret"))
    try:
        raise ValueError("connection failed " + quote(TOKEN, safe="") + " " + password)
    except ValueError:
        import sys
        record = logging.LogRecord("synthetic", logging.ERROR, __file__, 1,
                                   "request failed %s %s %s", (TOKEN, quote(password, safe=""), "test-only-webhook-secret"),
                                   sys.exc_info())
    output = formatter.format(record)
    for value in (TOKEN, password, "test-only-webhook-secret"):
        assert value not in output
        assert quote(value, safe="") not in output
    assert "request failed" in output and "ValueError" in output
    assert "connection failed" not in output


def test_formatter_omits_exception_inputs_that_may_contain_personal_data(launcher):
    try:
        raise ValueError("synthetic-private-message-body")
    except ValueError:
        import sys
        record = logging.LogRecord("test", logging.ERROR, __file__, 1, "Request failed", (), sys.exc_info())
    output = launcher.RedactingFormatter().format(record)
    assert "ValueError" in output
    assert "synthetic-private-message-body" not in output


@pytest.mark.parametrize("leaf", ["", ".venv", "outside"])
def test_stand_path_cannot_select_workspace_or_shared_runtime(launcher, tmp_path, monkeypatch, leaf):
    repo = tmp_path / "repo"
    (repo / ".venv").mkdir(parents=True)
    monkeypatch.setattr(launcher, "REPO", repo)
    target = tmp_path / "outside" if leaf == "outside" else repo / leaf
    with pytest.raises(launcher.TestStandError):
        launcher.checked_root(target)


def test_prepare_config_keeps_existing_bot_file_bytes(launcher, tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    root = repo / ".venv" / "telegram-test"
    root.mkdir(parents=True)
    monkeypatch.setattr(launcher, "REPO", repo)
    monkeypatch.setattr(launcher, "ensure_private_dir", lambda path: path.mkdir(parents=True, exist_ok=True))
    monkeypatch.setattr(launcher, "free_port", lambda start: start)
    original = f"# User wrote this file\nTEST_BOT_USERNAME={USERNAME}\nTEST_BOT_TOKEN={TOKEN}\n".encode("utf-8")
    (root / "bot.env").write_bytes(original)
    first = launcher.read_private_config(root)
    second = launcher.read_private_config(root)
    assert first == second
    assert first["workspace"] == str(repo)
    assert (root / "bot.env").read_bytes() == original


def test_foreign_workspace_config_is_rejected_before_acl_or_file_changes(launcher, tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    root = repo / ".venv" / "telegram-test"
    root.mkdir(parents=True)
    monkeypatch.setattr(launcher, "REPO", repo)
    acl_calls = []
    monkeypatch.setattr(launcher, "ensure_private_dir", lambda path: acl_calls.append(path))
    existing = json.dumps({"version": 1, "workspace": str(tmp_path / "other-workspace"), "instance_id": "d" * 32})
    (root / "runtime.json").write_text(existing, encoding="utf-8")
    with pytest.raises(launcher.TestStandError):
        launcher.read_private_config(root)
    assert acl_calls == []
    assert (root / "runtime.json").read_text(encoding="utf-8") == existing
    assert not (root / "bot.env").exists()


def test_new_test_bot_is_verified_without_mutating_telegram(launcher):
    bot = FakeTelegram()
    verified = asyncio.run(launcher.verify_test_bot(bot, USERNAME))
    assert verified == {"bot_id": 111111, "username": USERNAME}
    assert bot.writes == []


@pytest.mark.parametrize("username,bot_id,hook,prior", [
    ("main_bot", 111111, "", None),
    ("another_test_bot", 111111, "", None),
    (USERNAME, 111111, "https://primary.invalid/telegram/webhook", None),
    (USERNAME, 111111, "", {"bot_id": 222222}),
    (USERNAME, 111111, "https://primary.invalid/telegram/webhook",
     {"bot_id": 111111, "public_url": "https://primary.invalid", "webhook_url": "https://primary.invalid/telegram/webhook"}),
])
def test_verification_refuses_foreign_bot_or_hook_without_mutations(launcher, username, bot_id, hook, prior):
    bot = FakeTelegram(username=username, bot_id=bot_id, hook=hook)
    with pytest.raises(launcher.TestStandError):
        asyncio.run(launcher.verify_test_bot(bot, USERNAME, prior))
    assert bot.writes == []


def test_registration_rechecks_hook_after_preflight(launcher):
    bot = FakeTelegram()
    verified = asyncio.run(launcher.verify_test_bot(bot, USERNAME))
    bot.hook = "https://primary.invalid/telegram/webhook"
    with pytest.raises(launcher.TestStandError):
        asyncio.run(launcher.register_test_webhook(bot, verified, {},
                                                "https://synthetic.trycloudflare.com", "test-only-webhook-secret"))
    assert bot.writes == []


def test_only_verified_test_bot_gets_its_own_webhook(launcher):
    bot = FakeTelegram()
    verified = asyncio.run(launcher.verify_test_bot(bot, USERNAME))
    state = asyncio.run(launcher.register_test_webhook(bot, verified, {},
                                                     "https://synthetic.trycloudflare.com", "test-only-webhook-secret"))
    assert state["webhook_url"] == "https://synthetic.trycloudflare.com/telegram/webhook"
    assert bot.writes == [("set", state["webhook_url"], {"secret_token": "test-only-webhook-secret"})]
    assert asyncio.run(launcher.clear_test_webhook(bot, state)) is True
    assert bot.writes[-1] == ("delete", {})


@pytest.mark.parametrize("failures", [1, 6, 7])
def test_webhook_dns_retry_is_bounded(launcher, monkeypatch, failures):
    from aiogram.exceptions import TelegramBadRequest
    from aiogram.methods import SetWebhook

    class DelayedDNS(FakeTelegram):
        attempts = 0

        async def set_webhook(self, url, **kwargs):
            self.attempts += 1
            if self.attempts <= failures:
                raise TelegramBadRequest(method=SetWebhook(url=url), message="Bad Request: bad webhook: Failed to resolve host: Name or service not known")
            return await super().set_webhook(url, **kwargs)

    delays = []

    async def fake_sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(launcher.asyncio, "sleep", fake_sleep)
    bot = DelayedDNS()
    verified = {"bot_id": bot.identity.id, "username": USERNAME}
    operation = launcher.register_test_webhook(bot, verified, {}, "https://synthetic.trycloudflare.com", "synthetic-secret")
    if failures == 7:
        with pytest.raises(launcher.TestStandError, match="7 attempts"):
            asyncio.run(operation)
        assert bot.writes == []
    else:
        result = asyncio.run(operation)
        assert result["webhook_url"] == bot.hook
        assert len(bot.writes) == 1
    assert bot.attempts == min(failures + 1, 7)
    assert delays == [5] * min(failures, 6)


def test_webhook_retry_rechecks_foreign_hook(launcher, monkeypatch):
    from aiogram.exceptions import TelegramBadRequest
    from aiogram.methods import SetWebhook

    class ChangedHook(FakeTelegram):
        attempts = 0

        async def set_webhook(self, url, **kwargs):
            self.attempts += 1
            self.hook = "https://foreign.invalid/telegram/webhook"
            raise TelegramBadRequest(method=SetWebhook(url=url), message="Failed to resolve host")

    async def fake_sleep(delay):
        pass

    monkeypatch.setattr(launcher.asyncio, "sleep", fake_sleep)
    bot = ChangedHook()
    with pytest.raises(launcher.TestStandError, match="another webhook"):
        asyncio.run(launcher.register_test_webhook(bot, {"bot_id": bot.identity.id, "username": USERNAME}, {},
                                                "https://synthetic.trycloudflare.com", "synthetic-secret"))
    assert bot.attempts == 1
    assert bot.hook == "https://foreign.invalid/telegram/webhook"


def test_webhook_other_bad_request_is_not_retried(launcher, monkeypatch):
    from aiogram.exceptions import TelegramBadRequest
    from aiogram.methods import SetWebhook

    async def rejected(url, **kwargs):
        raise TelegramBadRequest(method=SetWebhook(url=url), message="Bad Request: certificate rejected")

    async def forbidden_sleep(delay):
        pytest.fail("A non-DNS rejection was retried")

    bot = FakeTelegram()
    monkeypatch.setattr(bot, "set_webhook", rejected)
    monkeypatch.setattr(launcher.asyncio, "sleep", forbidden_sleep)
    with pytest.raises(TelegramBadRequest, match="certificate rejected"):
        asyncio.run(launcher.register_test_webhook(bot, {"bot_id": bot.identity.id, "username": USERNAME}, {},
                                                "https://synthetic.trycloudflare.com", "synthetic-secret"))


def test_tunnel_waits_through_dns_edge_errors_and_non_health_response(launcher, monkeypatch):
    from urllib.error import HTTPError, URLError

    class Response(io.BytesIO):
        status = 200

    replies = iter([URLError("Synthetic DNS not ready"), HTTPError("synthetic", 502, "edge not ready", {}, None),
                    b"<html>not ready</html>", b"[]", b'{"ok":false}', b'{"ok":true}'])
    calls, delays = [], []

    def fake_open(url, timeout):
        calls.append((url, timeout))
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return Response(reply)

    monkeypatch.setattr(launcher, "build_opener", lambda *args: SimpleNamespace(open=fake_open))
    monkeypatch.setattr(launcher.time, "monotonic", lambda: 0)
    monkeypatch.setattr(launcher.time, "sleep", delays.append)
    launcher.wait_public_health("https://synthetic.trycloudflare.com", SimpleNamespace(poll=lambda: None))
    assert calls == [("https://synthetic.trycloudflare.com/health", 5)] * 6
    assert delays == [2] * 5


@pytest.mark.parametrize("exited", [False, True], ids=["timeout", "exited"])
def test_unreachable_tunnel_never_becomes_ready(launcher, monkeypatch, exited):
    from urllib.error import URLError

    clock = [0]

    def advance(delay):
        clock[0] += delay

    def failed_open(url, timeout):
        raise URLError("Synthetic DNS failure")

    monkeypatch.setattr(launcher, "build_opener", lambda *args: SimpleNamespace(open=failed_open))
    monkeypatch.setattr(launcher.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(launcher.time, "sleep", advance)
    with pytest.raises(launcher.TestStandError, match="exited|no webhook"):
        launcher.wait_public_health("https://synthetic.trycloudflare.com", SimpleNamespace(poll=lambda: 1 if exited else None), timeout=4)
    assert clock[0] == (0 if exited else 4)


def test_tunnel_health_refuses_foreign_url_before_network(launcher, monkeypatch):
    def forbidden(*args):
        pytest.fail("A foreign health URL reached the network")

    monkeypatch.setattr(launcher, "build_opener", forbidden)
    with pytest.raises(launcher.TestStandError):
        launcher.wait_public_health("https://foreign.invalid", SimpleNamespace(poll=lambda: None))


@pytest.mark.parametrize("reachable", [False, True], ids=["tunnel-not-ready", "tunnel-ready"])
def test_start_registers_only_after_public_health(launcher, stand_config, tmp_path, monkeypatch, reachable):
    import aiogram
    pg = importlib.import_module("telegram_test_pg")
    events = []
    url = "https://synthetic.trycloudflare.com"
    bot = FakeTelegram()

    async def close():
        pass

    async def verify(*args):
        return {"bot_id": bot.identity.id, "username": USERNAME}

    async def register(*args):
        assert "public-health" in events and reachable
        events.append("register")
        return {"bot_id": bot.identity.id, "username": USERNAME,
                "public_url": url, "webhook_url": url + "/telegram/webhook"}

    def spawn(command, root, name, env):
        if name.endswith("/tunnel"):
            assert command[command.index("--protocol") + 1] == "http2"
            path = root / f"{name}.log"
            path.parent.mkdir(parents=True)
            path.write_text(url, encoding="utf-8")
            return SimpleNamespace(pid=1, poll=lambda: None)
        session = json.loads((root / "session-config.json").read_text(encoding="utf-8"))
        launcher.write_json(root / "server-starting.json", {"session_id": session["session_id"], "process": {"pid": 2}})
        launcher.write_json(root / "server-ready.json", {"session_id": session["session_id"]})
        return SimpleNamespace(pid=2, poll=lambda: None)

    def public_health(*args):
        # Local API is already healthy, but the public URL may still fail.
        assert "webhook_url" not in launcher.read_state(tmp_path)
        events.append("public-health")
        if not reachable:
            raise launcher.TestStandError("Synthetic public tunnel timeout")

    bot.session = SimpleNamespace(close=close)
    monkeypatch.setattr(aiogram, "Bot", lambda token: bot)
    monkeypatch.setattr(launcher, "load_bot_config", lambda path: {"username": USERNAME, "token": TOKEN})
    monkeypatch.setattr(launcher, "configure_logging", lambda *args: None)
    monkeypatch.setattr(launcher, "verify_test_bot", verify)
    monkeypatch.setattr(launcher, "register_test_webhook", register)
    monkeypatch.setattr(launcher, "download_tunnel", lambda root: root / "synthetic-cloudflared.exe")
    monkeypatch.setattr(launcher, "spawn_logged", spawn)
    monkeypatch.setattr(launcher, "process_identity", lambda pid: {"pid": pid})
    monkeypatch.setattr(launcher, "owned_process", lambda info: False)
    monkeypatch.setattr(launcher, "build_opener", lambda *args: SimpleNamespace(open=lambda *args, **kwargs: io.BytesIO(b'{"ok":true}')))
    monkeypatch.setattr(launcher, "wait_public_health", public_health)
    monkeypatch.setattr(launcher, "stop", lambda *args, **kwargs: events.append("stop"))
    for name in ("start_postgres", "ensure_database", "backup_database"):
        monkeypatch.setattr(pg, name, lambda *args: True)
    if reachable:
        launcher.start(tmp_path, stand_config)
        assert events == ["public-health", "register"]
    else:
        with pytest.raises(launcher.TestStandError, match="Synthetic public tunnel timeout"):
            launcher.start(tmp_path, stand_config)
        assert events == ["public-health", "stop"]


@pytest.mark.parametrize("username,bot_id,hook", [
    (USERNAME, 222222, "https://synthetic.trycloudflare.com/telegram/webhook"),
    (USERNAME, 111111, "https://primary.invalid/telegram/webhook"),
    ("main_bot", 111111, "https://synthetic.trycloudflare.com/telegram/webhook"),
])
def test_cleanup_does_not_delete_another_bot_or_hook(launcher, username, bot_id, hook):
    bot = FakeTelegram(username=username, bot_id=bot_id, hook=hook)
    state = {"bot_id": 111111, "username": username, "public_url": "https://synthetic.trycloudflare.com",
             "webhook_url": "https://synthetic.trycloudflare.com/telegram/webhook"}
    assert asyncio.run(launcher.clear_test_webhook(bot, state)) is False
    assert bot.writes == []


def test_child_environment_drops_application_and_connection_secrets(launcher, tmp_path, monkeypatch):
    inherited = {"BOT_TOKEN": "fake-main-token", "DATABASE_URL": "fake-main-database",
                 "PGPASSWORD": "fake-main-password", "TUNNEL_TOKEN": "fake-main-tunnel",
                 "HTTP_PROXY": "http://fake-secret-proxy.invalid", "SSH_AUTH_SOCK": "fake-agent"}
    for key, value in inherited.items():
        monkeypatch.setenv(key, value)
    environment = launcher.child_environment(tmp_path)
    assert not any(key in environment for key in inherited)
    assert not any(value in environment.values() for value in inherited.values())


def test_missing_token_prevents_database_tunnel_or_bot_start(launcher, stand_config, tmp_path, monkeypatch):
    pg = importlib.import_module("telegram_test_pg")
    (tmp_path / "bot.env").write_text("TEST_BOT_USERNAME=\nTEST_BOT_TOKEN=\n", encoding="utf-8")

    def forbidden(*args, **kwargs):
        pytest.fail("A missing test token reached an external or native startup action")

    for name in ("start_postgres", "ensure_database", "backup_database"):
        monkeypatch.setattr(pg, name, forbidden)
    monkeypatch.setattr(launcher, "download_tunnel", forbidden)
    monkeypatch.setattr(launcher, "spawn_logged", forbidden)
    with pytest.raises(launcher.TestStandError):
        launcher.start(tmp_path, stand_config)


def test_stop_preserves_private_bot_file_database_and_backups(launcher, stand_config, tmp_path, monkeypatch):
    pg = importlib.import_module("telegram_test_pg")
    state = {"instance_id": stand_config["instance_id"], "session_id": "synthetic-session", "offline": True}
    launcher.write_json(tmp_path / "processes.json", state)
    protected = {tmp_path / "bot.env": b"synthetic private bot file",
                 tmp_path / "postgres" / "data" / "facts.bin": b"synthetic recorded facts",
                 tmp_path / "backups" / "retained.dump": b"synthetic backup"}
    for path, contents in protected.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
    launcher.write_json(tmp_path / "session-config.json", {"token": TOKEN})
    stopped = []
    monkeypatch.setattr(pg, "stop_postgres", lambda root, cfg: stopped.append(root))
    monkeypatch.setattr(launcher, "owned_process", lambda info: False)
    monkeypatch.setattr(launcher, "terminate_owned", lambda info: None)
    launcher.stop(tmp_path, stand_config)
    assert stopped == [tmp_path]
    assert all(path.read_bytes() == contents for path, contents in protected.items())
    assert not (tmp_path / "session-config.json").exists()


def test_stop_refuses_a_foreign_instance_before_process_or_data_changes(launcher, stand_config, tmp_path, monkeypatch):
    pg = importlib.import_module("telegram_test_pg")
    launcher.write_json(tmp_path / "processes.json", {"instance_id": "foreign-instance"})
    before = (tmp_path / "processes.json").read_bytes()

    def forbidden(*args, **kwargs):
        pytest.fail("A foreign stand reached process shutdown")

    monkeypatch.setattr(pg, "stop_postgres", forbidden)
    monkeypatch.setattr(launcher, "terminate_owned", forbidden)
    with pytest.raises(launcher.TestStandError):
        launcher.stop(tmp_path, stand_config)
    assert (tmp_path / "processes.json").read_bytes() == before
    assert not (tmp_path / "stop-server").exists()


@pytest.mark.parametrize("started_here", [True, False], ids=["newly-started", "preexisting"])
def test_backup_failure_only_stops_postgresql_started_by_this_attempt(launcher, stand_config, tmp_path, monkeypatch, started_here):
    pg = importlib.import_module("telegram_test_pg")
    old_state = {"instance_id": stand_config["instance_id"], "offline": True, "session_id": "previous-session"}
    launcher.write_json(tmp_path / "processes.json", old_state)
    before = (tmp_path / "processes.json").read_bytes()
    events = []
    monkeypatch.setattr(launcher, "configure_logging", lambda *args: None)
    monkeypatch.setattr(pg, "start_postgres", lambda root, cfg: events.append("start") or started_here)
    monkeypatch.setattr(pg, "ensure_database", lambda root, cfg: events.append("database"))

    def failed_backup(root, cfg):
        events.append("backup")
        raise RuntimeError("Synthetic backup failure")

    monkeypatch.setattr(pg, "backup_database", failed_backup)
    monkeypatch.setattr(pg, "stop_postgres", lambda root, cfg: events.append("stop"))

    def forbidden(*args, **kwargs):
        pytest.fail("A failed database backup reached API or tunnel startup")

    monkeypatch.setattr(launcher, "spawn_logged", forbidden)
    with pytest.raises(RuntimeError, match="Synthetic backup failure"):
        launcher.start(tmp_path, stand_config, offline=True)
    assert events == ["start", "database", "backup", *(["stop"] if started_here else [])]
    assert (tmp_path / "processes.json").read_bytes() == before
    assert not (tmp_path / "session-config.json").exists()


@pytest.mark.parametrize("offline", [True, False], ids=["offline", "online"])
def test_start_preserves_unresolved_online_cleanup_credentials(launcher, stand_config, tmp_path, monkeypatch, offline):
    pg = importlib.import_module("telegram_test_pg")
    old_state = {"instance_id": stand_config["instance_id"], "session_id": "online-session", "offline": False,
                 "bot_id": 111111, "username": USERNAME,
                 "public_url": "https://synthetic.trycloudflare.com",
                 "webhook_url": "https://synthetic.trycloudflare.com/telegram/webhook"}
    launcher.write_json(tmp_path / "processes.json", old_state)
    launcher.write_json(tmp_path / "session-config.json", {"token": TOKEN, "session_id": "online-session"})
    before = {name: (tmp_path / name).read_bytes() for name in ("processes.json", "session-config.json")}

    def forbidden(*args, **kwargs):
        pytest.fail("Unconfirmed webhook cleanup reached a new startup action")

    for name in ("start_postgres", "ensure_database", "backup_database", "stop_postgres"):
        monkeypatch.setattr(pg, name, forbidden)
    monkeypatch.setattr(launcher, "spawn_logged", forbidden)
    monkeypatch.setattr(launcher, "configure_logging", forbidden)
    with pytest.raises(launcher.TestStandError, match="cleanup"):
        launcher.start(tmp_path, stand_config, offline=offline)
    assert all((tmp_path / name).read_bytes() == data for name, data in before.items())


def test_cleanup_of_already_disconnected_verified_test_bot_is_successful(launcher):
    bot = FakeTelegram(hook="")
    state = {"bot_id": 111111, "username": USERNAME,
             "public_url": "https://synthetic.trycloudflare.com",
             "webhook_url": "https://synthetic.trycloudflare.com/telegram/webhook"}
    assert asyncio.run(launcher.clear_test_webhook(bot, state)) is True
    assert bot.writes == []


def test_reminder_setting_preserves_default_and_supports_explicit_test_disable(monkeypatch):
    monkeypatch.delenv("REMINDERS_ENABLED", raising=False)
    assert config.Settings(_env_file=None).reminders_enabled is True
    assert config.Settings(_env_file=None, reminders_enabled=False).reminders_enabled is False


@pytest.mark.parametrize("mode", ["development", "production"])
@pytest.mark.parametrize("enabled", [False, True])
def test_lifespan_only_runs_automatic_reminders_when_enabled(monkeypatch, mode, enabled):
    settings = SimpleNamespace(
        app_env=mode, bot_token=TOKEN, public_url="https://synthetic.trycloudflare.com",
        webhook_secret="test-only-webhook-secret", database_url="postgresql+psycopg://test@127.0.0.1/test",
        reminders_enabled=enabled,
    )
    migrations, bots, reminders, cancelled = [], [], [], []
    isolated_engine = object()

    class FakeSession:
        closed = False

        async def close(self):
            self.closed = True

    class FakeBot:
        def __init__(self, token):
            assert token == TOKEN
            self.session = FakeSession()
            self.webhooks = []
            bots.append(self)

        async def set_webhook(self, url, **kwargs):
            self.webhooks.append((url, kwargs))

    async def reminder(bot):
        reminders.append(bot)
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(bot)

    monkeypatch.setattr(main, "get_settings", lambda: settings)
    monkeypatch.setattr(main, "engine", isolated_engine)
    monkeypatch.setattr(main, "migrate", lambda engine: migrations.append(engine))
    monkeypatch.setattr(main, "Bot", FakeBot)
    monkeypatch.setattr(main, "reminder_loop", reminder)
    fake_app = SimpleNamespace(state=SimpleNamespace())

    async def exercise():
        async with main.lifespan(fake_app):
            await asyncio.sleep(0)
            assert migrations == [isolated_engine]
            assert fake_app.state.bot is bots[0]
            assert reminders == ([bots[0]] if enabled else [])
            assert bots[0].session.closed is False
        assert bots[0].session.closed is True

    asyncio.run(exercise())
    assert cancelled == ([bots[0]] if enabled else [])
    assert bots[0].webhooks == ([
        ("https://synthetic.trycloudflare.com/telegram/webhook",
         {"secret_token": "test-only-webhook-secret"})
    ] if mode == "production" else [])


@pytest.mark.parametrize("invalid", [
    {"bot_token": ""},
    {"public_url": "http://127.0.0.1:58081"},
    {"webhook_secret": ""},
    {"database_url": "sqlite:///:memory:"},
], ids=["missing-token", "not-https", "missing-webhook-secret", "not-postgresql"])
def test_production_validation_still_rejects_invalid_settings_before_side_effects(monkeypatch, invalid):
    values = dict(app_env="production", bot_token=TOKEN,
                  public_url="https://synthetic.trycloudflare.com",
                  webhook_secret="test-only-webhook-secret",
                  database_url="postgresql+psycopg://test@127.0.0.1/test",
                  reminders_enabled=False)
    values.update(invalid)
    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(**values))

    def forbidden(*args, **kwargs):
        pytest.fail("Invalid production settings reached migration or Bot construction")

    monkeypatch.setattr(main, "migrate", forbidden)
    monkeypatch.setattr(main, "Bot", forbidden)

    async def exercise():
        with pytest.raises(RuntimeError, match="Production requires"):
            async with main.lifespan(SimpleNamespace(state=SimpleNamespace())):
                pytest.fail("Invalid settings entered the lifespan")

    asyncio.run(exercise())
