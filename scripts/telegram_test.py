"""Owned local Telegram stand. Preparation is offline except binary download.

The normal app and authentication are reused. Explicit Settings never read the
production .env or inherited application variables. Only start (without
--offline) exposes a tunnel and registers the verified dedicated test bot.
"""

import argparse
import asyncio
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import subprocess
import sys
import time
from urllib.parse import quote
from urllib.request import urlopen
from urllib.request import build_opener, ProxyHandler
from uuid import uuid4

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = REPO / ".venv" / "telegram-test"
CLOUDFLARED_VERSION = "2026.10.7"
CLOUDFLARED_SHA256 = "2493dbc168923bb3e59e5e7716f71deced92992eea9acd6e9d74f84ac7751343"
CLOUDFLARED_URL = f"https://github.com/cloudflare/cloudflared/releases/download/{CLOUDFLARED_VERSION}/cloudflared-windows-amd64.exe"
URL_PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com\Z")
BOT_TEMPLATE = "# Only the NEW dedicated test bot; never the main bot.\nTEST_BOT_USERNAME=\nTEST_BOT_TOKEN=\n"
HIDDEN = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


class TestStandError(RuntimeError):
    pass


class RedactingFormatter(logging.Formatter):
    def __init__(self, sensitive=()):
        super().__init__("%(levelname)s %(name)s: %(message)s")
        self.sensitive = sorted({part for value in sensitive if value
                                 for part in (str(value), quote(str(value), safe=""))}, key=len, reverse=True)

    def format(self, record):
        result = super().format(record)
        for value in self.sensitive:
            result = result.replace(value, "[REDACTED]")
        return result

    def formatException(self, exc_info):
        # Validation/SQL exceptions can embed Telegram payloads or workout
        # inputs. Keep the type, not raw personal data or arguments, in logs.
        return f"{exc_info[0].__name__}: details omitted in test logs"


def configure_logging(cfg, token=""):
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter((token, cfg["db_password"], cfg["webhook_secret"])))
    logging.getLogger().handlers = [handler]
    logging.getLogger().setLevel(logging.INFO)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "aiogram"):
        logger = logging.getLogger(name)
        logger.handlers, logger.propagate = [], True


def write_json(path, value):
    temporary = path.with_name(path.name + ".new")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def ensure_private_dir(root):
    root.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        # Apply only to this owned stand directory; do not change parent ACLs.
        literal = "'" + str(root).replace("'", "''") + "'"
        command = ("$ErrorActionPreference='Stop'; $p=" + literal + "; $a=[System.IO.Directory]::GetAccessControl($p); $a.SetAccessRuleProtection($true,$false); "
                   "$s=[Security.Principal.WindowsIdentity]::GetCurrent().User; "
                   "$a.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($s,'FullControl','ContainerInherit,ObjectInherit','None','Allow')); "
                   "$a.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new('S-1-5-18'),'FullControl','ContainerInherit,ObjectInherit','None','Allow')); "
                   "[System.IO.Directory]::SetAccessControl($p,$a)")
        # Only an escaped literal filesystem path is shell source; never a secret.
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                                env=child_environment(root), capture_output=True, creationflags=HIDDEN)
        if result.returncode:
            raise TestStandError("Could not restrict the private stand directory ACL")


def checked_root(root=ROOT):
    root = Path(root)
    venv = (REPO / ".venv").resolve()
    if (root.is_symlink() or root.resolve() == venv or not root.resolve().is_relative_to(venv)
            or any(item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction())
                   for item in (root, *root.parents) if item != REPO.parent)):
        raise TestStandError("Stand path must stay inside this workspace .venv")
    return root.resolve()


def private_path(root, relative):
    path = root / relative
    if (path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())
            or not path.resolve().is_relative_to(root.resolve())):
        raise TestStandError("A private stand file escapes its owned directory")
    for parent in path.parents:
        if parent == root:
            break
        if parent.is_symlink() or (hasattr(parent, "is_junction") and parent.is_junction()):
            raise TestStandError("A private stand file contains a reparse point")
    return path


def free_port(start):
    for port in range(start, start + 20):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
                return port
            except OSError:
                pass
    raise TestStandError("No free loopback port in the stand range")


def read_private_config(root=ROOT):
    root = checked_root(root)
    path = private_path(root, "runtime.json")
    marker = private_path(root, ".managed.json")
    private_path(root, "bot.env")
    private_path(root, "processes.json")
    private_path(root, "session-config.json")
    if path.exists():
        cfg = json.loads(path.read_text(encoding="utf-8"))
        if cfg.get("workspace") != str(REPO) or cfg.get("version") != 1:
            raise TestStandError("Existing stand belongs to a different workspace/version; nothing changed")
    else:
        if marker.exists() or (root / "postgres/data").exists():
            raise TestStandError("Existing stand data has no matching runtime config; nothing changed")
        cfg = {"version": 1, "workspace": str(REPO), "instance_id": uuid4().hex,
               "pg_port": free_port(55444), "http_port": free_port(58081),
               "db_name": "gymbot_telegram", "db_user": "gymbot_tg_test",
               "db_password": secrets.token_hex(24), "webhook_secret": secrets.token_hex(32)}
    expected = {"workspace": str(REPO), "instance_id": cfg["instance_id"]}
    if marker.exists() and json.loads(marker.read_text(encoding="utf-8")) != expected:
        raise TestStandError("Stand ownership marker does not match")
    ensure_private_dir(root)
    token_path = root / "bot.env"
    if not token_path.exists():
        token_path.write_text(BOT_TEMPLATE, encoding="utf-8")
    if not path.exists():
        write_json(path, cfg)
    if not marker.exists():
        write_json(marker, expected)
    return cfg


def load_bot_config(path):
    from aiogram.utils.token import validate_token
    values = {}
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or key not in ("TEST_BOT_USERNAME", "TEST_BOT_TOKEN") or key in values:
            raise TestStandError("bot.env must contain only TEST_BOT_USERNAME and TEST_BOT_TOKEN once")
        values[key] = value
    username = values.get("TEST_BOT_USERNAME", "").lstrip("@")
    token = values.get("TEST_BOT_TOKEN", "")
    if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", username) or not username.lower().endswith("_test_bot"):
        raise TestStandError("Fill TEST_BOT_USERNAME with the new bot username ending _test_bot")
    try:
        validate_token(token)
    except Exception:
        raise TestStandError("Fill TEST_BOT_TOKEN locally from BotFather; do not send it in chat") from None
    return {"username": username, "token": token}


def build_settings(cfg, token, public_url, offline=False):
    from app.config import Settings
    from telegram_test_pg import database_url
    if not offline and not URL_PATTERN.fullmatch(public_url):
        raise TestStandError("Online stand requires its own temporary trycloudflare HTTPS URL")
    # All current application settings are explicit constructor arguments; they
    # override environment variables, and dotenv loading is disabled entirely.
    return Settings(_env_file=None, app_env="development", bot_token="" if offline else token,
                    public_url=f'http://127.0.0.1:{cfg["http_port"]}' if offline else public_url,
                    database_url=database_url(cfg), webhook_secret=cfg["webhook_secret"],
                    dev_telegram_id=0, reminders_enabled=False)


async def verify_test_bot(bot, expected_username, prior_state=None):
    me = await bot.get_me()
    if not me.username or me.username.casefold() != expected_username.casefold() or not me.username.lower().endswith("_test_bot"):
        raise TestStandError("Token does not belong to the named dedicated test bot; no webhook changed")
    prior_state = prior_state or {}
    if prior_state.get("bot_id") not in (None, me.id):
        raise TestStandError("Previous stand belongs to another bot; no webhook changed")
    hook = await bot.get_webhook_info()
    if hook.url:
        prior_url = prior_state.get("public_url", "")
        if (not URL_PATTERN.fullmatch(prior_url) or prior_state.get("webhook_url") != prior_url + "/telegram/webhook"
                or hook.url != prior_state["webhook_url"]):
            raise TestStandError("This bot already has another webhook; it will not be replaced")
    return {"bot_id": me.id, "username": me.username}


async def register_test_webhook(bot, verified, state, url, secret):
    if not URL_PATTERN.fullmatch(url):
        raise TestStandError("Refusing a non-test tunnel URL")
    current = await verify_test_bot(bot, verified["username"], state)
    if current["bot_id"] != verified["bot_id"]:
        raise TestStandError("Bot identity changed")
    target = url + "/telegram/webhook"
    if not await bot.set_webhook(target, secret_token=secret):
        raise TestStandError("Telegram did not accept the test webhook")
    if (await bot.get_webhook_info()).url != target:
        raise TestStandError("Telegram did not confirm the test webhook")
    return {**verified, "public_url": url, "webhook_url": target}


async def clear_test_webhook(bot, state):
    if not state.get("webhook_url") or not URL_PATTERN.fullmatch(state.get("public_url", "")):
        return False
    me = await bot.get_me()
    if (me.id != state.get("bot_id") or not (me.username or "").lower().endswith("_test_bot")
            or (me.username or "").casefold() != state.get("username", "").casefold()):
        return False
    hook = await bot.get_webhook_info()
    if not hook.url:
        return True  # The same verified bot is already disconnected.
    if hook.url != state["webhook_url"] or hook.url != state["public_url"] + "/telegram/webhook":
        return False
    return bool(await bot.delete_webhook())


def process_identity(pid):
    if os.name != "nt":
        raise TestStandError("This local launcher currently supports Windows only")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes, kernel.OpenProcess.restype = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return None
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        size, image = wintypes.DWORD(32768), ctypes.create_unicode_buffer(32768)
        if not kernel.GetProcessTimes(handle, *[ctypes.byref(item) for item in times]) or not kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size)):
            return None
        return {"pid": int(pid), "started": times[0].dwHighDateTime << 32 | times[0].dwLowDateTime,
                "exe": os.path.normcase(os.path.realpath(image.value))}
    finally:
        kernel.CloseHandle(handle)


def owned_process(info):
    return bool(info and process_identity(info["pid"]) == info)


def terminate_owned(info):
    if owned_process(info):
        os.kill(info["pid"], signal.SIGTERM)


def read_state(root):
    path = root / "processes.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def download_tunnel(root):
    path = private_path(root, "bin/cloudflared.exe")
    path.parent.mkdir(exist_ok=True)
    if not path.exists():
        temporary = path.with_suffix(".download")
        with urlopen(CLOUDFLARED_URL, timeout=60) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != CLOUDFLARED_SHA256:
            raise TestStandError("Official cloudflared checksum mismatch; binary will not run")
        temporary.replace(path)
    if hashlib.sha256(path.read_bytes()).hexdigest() != CLOUDFLARED_SHA256:
        raise TestStandError("Existing cloudflared checksum mismatch; binary will not run")
    (root / "cloudflared-empty.yml").write_text("{}\n", encoding="utf-8")
    return path


def build_frontend(root):
    typescript = REPO / "frontend/node_modules/typescript/bin/tsc"
    if not typescript.exists():
        raise TestStandError("Existing frontend dependencies are missing; follow README setup first")
    output = private_path(root, "client-dist")
    marker = private_path(root, "client-build-marker.json")
    if output.exists() and not marker.exists():
        raise TestStandError("Existing client output is not managed by this stand")
    env = child_environment(root)
    env["VITE_DEV_TELEGRAM_ID"] = ""
    with (root / "build.log").open("w", encoding="utf-8") as log:
        commands = [["node", str(typescript), "--noEmit"],
                    ["node", "--input-type=module", "-e",
                     "import {build} from './node_modules/vite/dist/node/index.js'; await build({envDir:false,mode:'telegram-test',build:{outDir:process.argv[1],emptyOutDir:false}})", str(output)]]
        for command in commands:
            result = subprocess.run(command, cwd=REPO / "frontend", env=env, stdout=log, stderr=log, creationflags=HIDDEN)
            if result.returncode:
                raise TestStandError("Frontend build failed; inspect the private build.log")
    write_json(marker, {"workspace": str(REPO), "output": str(output)})


@contextmanager
def operation_lock(root):
    path = root / "operation.lock"
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise TestStandError("Another stand operation is active; inspect operation.lock before retry") from None
    try:
        os.close(descriptor)
        yield
    finally:
        path.unlink()


def prepare(root, cfg):
    from telegram_test_pg import ensure_cluster
    download_tunnel(root)
    ensure_cluster(root, cfg)
    build_frontend(root)


async def serve(root, cfg, offline):
    session = json.loads((root / "session-config.json").read_text(encoding="utf-8"))
    if session["instance_id"] != cfg["instance_id"] or bool(session["offline"]) != offline:
        raise TestStandError("Server session marker does not match the owned stand")
    configure_logging(cfg, session["token"])
    settings = build_settings(cfg, session["token"], session["public_url"], offline)
    # The isolated entry point installs its explicit Settings before db/auth/bot
    # are imported. Normal `uvicorn app.main:app` configuration is unchanged.
    from app import config
    config.get_settings = lambda: settings
    from app.main import app
    from fastapi.staticfiles import StaticFiles
    import uvicorn
    app.mount("/", StaticFiles(directory=str(root / "client-dist"), html=True), name="telegram-test-static")
    identity = process_identity(os.getpid())
    write_json(root / "server-starting.json", {"instance_id": cfg["instance_id"], "session_id": session["session_id"], "process": identity})
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=cfg["http_port"], log_config=None, access_log=False))

    async def watch():
        ready_written = False
        while not server.should_exit:
            if server.started and not ready_written:
                write_json(root / "server-ready.json", {"session_id": session["session_id"], "process": identity})
                ready_written = True
            stop = root / "stop-server"
            if stop.exists() and stop.read_text(encoding="utf-8") == session["session_id"]:
                server.should_exit = True
            await asyncio.sleep(.25)

    task = asyncio.create_task(watch())
    try:
        await server.serve()
    finally:
        task.cancel()
        from contextlib import suppress
        with suppress(asyncio.CancelledError):
            await task


def spawn_logged(command, root, name, env=None):
    path = private_path(root, f"{name}.log")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as log:
        return subprocess.Popen(command, cwd=REPO, env=env, stdout=log, stderr=log, creationflags=HIDDEN)


def child_environment(root):
    # No inherited bot/database/cloud credentials, proxy credentials, named
    # tunnels, SSH uploads or PGOPTIONS can affect an isolated child process.
    allowed = {"SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "COMSPEC", "USERPROFILE",
               "HOMEDRIVE", "HOMEPATH", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE"}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    temporary = root / "tmp"
    temporary.mkdir(exist_ok=True)
    env.update(TEMP=str(temporary), TMP=str(temporary), PYTHONUTF8="1")
    return env


def start(root, cfg, offline=False):
    from telegram_test_pg import start_postgres, ensure_database, backup_database, stop_postgres
    old = read_state(root)
    if old.get("instance_id") not in (None, cfg["instance_id"]):
        raise TestStandError("Previous process state belongs to another stand")
    if owned_process(old.get("api")) or owned_process(old.get("tunnel")):
        raise TestStandError("Stand is already running; use status or stop first")
    if (root / "session-config.json").exists() and old.get("webhook_url") and not old.get("offline", True):
        raise TestStandError("Previous test webhook cleanup is not confirmed; retry stop before startup")
    bot_cfg = {"username": "", "token": ""} if offline else load_bot_config(root / "bot.env")
    configure_logging(cfg, bot_cfg["token"])
    verified = {}
    if not offline:
        from aiogram import Bot
        async def verify():
            bot = Bot(bot_cfg["token"])
            try:
                return await verify_test_bot(bot, bot_cfg["username"], old)
            finally:
                await bot.session.close()
        verified = asyncio.run(verify())
    started_here = False
    try:
        started_here = start_postgres(root, cfg)
        ensure_database(root, cfg)
        backup_database(root, cfg)
    except BaseException:
        if started_here:
            stop_postgres(root, cfg)
        raise
    state = {"instance_id": cfg["instance_id"], "session_id": uuid4().hex, "offline": offline}
    log_dir = f'logs/{state["session_id"]}'
    state["log_dir"] = log_dir
    session = {**state, "token": bot_cfg["token"], "public_url": f'http://127.0.0.1:{cfg["http_port"]}'}
    write_json(root / "processes.json", state)
    try:
        if not offline:
            tunnel = download_tunnel(root)
            env = child_environment(root)
            process = spawn_logged([str(tunnel), "tunnel", "--config", str(root / "cloudflared-empty.yml"),
                                    "--origincert", str(root / "unused-origin-cert.pem"),
                                    "--no-autoupdate", "--metrics", "127.0.0.1:0", "--url", session["public_url"]], root, f"{log_dir}/tunnel", env)
            state["tunnel"] = process_identity(process.pid)
            write_json(root / "processes.json", state)
            url = None
            for _ in range(180):
                text = (root / f"{log_dir}/tunnel.log").read_text(encoding="utf-8", errors="replace")
                urls = re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", text)
                if urls:
                    url = urls[-1]
                    break
                if process.poll() is not None:
                    break
                time.sleep(.25)
            if not url:
                raise TestStandError("Own HTTPS tunnel did not become ready; inspect private tunnel.log")
            session["public_url"] = url
        write_json(root / "session-config.json", session)
        launcher = spawn_logged([sys.executable, str(Path(__file__).resolve()), "_serve", *( ["--offline"] if offline else [])], root, f"{log_dir}/api", child_environment(root))
        state["api_launcher"] = process_identity(launcher.pid)
        write_json(root / "processes.json", state)
        for _ in range(180):
            starting = root / "server-starting.json"
            if starting.exists():
                marker = json.loads(starting.read_text(encoding="utf-8"))
                if marker["session_id"] == state["session_id"]:
                    state["api"] = marker["process"]
            ready = root / "server-ready.json"
            if ready.exists() and json.loads(ready.read_text(encoding="utf-8"))["session_id"] == state["session_id"]:
                break
            if launcher.poll() is not None:
                raise TestStandError("Own API did not start; inspect the redacted private api.log")
            time.sleep(.25)
        else:
            raise TestStandError("Own API startup timed out")
        write_json(root / "processes.json", state)
        with build_opener(ProxyHandler({})).open(f'http://127.0.0.1:{cfg["http_port"]}/health', timeout=5) as health:
            if not json.load(health).get("ok"):
                raise TestStandError("Own API health check failed")
        if not offline:
            state.update(**verified, public_url=session["public_url"], webhook_url=session["public_url"] + "/telegram/webhook")
            write_json(root / "processes.json", state)
            async def register():
                bot = Bot(bot_cfg["token"])
                try:
                    return await register_test_webhook(bot, verified, old, session["public_url"], cfg["webhook_secret"])
                finally:
                    await bot.session.close()
            state.update(asyncio.run(register()))
            write_json(root / "processes.json", state)
        print(f'Stand ready: {session["public_url"]}')
        print("Offline, no bot or tunnel" if offline else f'Test bot: @{state["username"]}; automatic reminders disabled')
    except BaseException:
        write_json(root / "processes.json", state)
        stop(root, cfg, stop_database=started_here)
        raise


def stop(root, cfg, *, stop_database=True):
    from telegram_test_pg import stop_postgres
    state = read_state(root)
    if state.get("instance_id") not in (None, cfg["instance_id"]):
        raise TestStandError("Refusing to stop another stand")
    session_path = root / "session-config.json"
    credentials_can_clear = state.get("offline", True) or not state.get("webhook_url")
    if not state.get("offline", True) and state.get("webhook_url") and session_path.exists():
        from aiogram import Bot
        session = json.loads(session_path.read_text(encoding="utf-8"))
        configure_logging(cfg, session["token"])
        async def clear():
            bot = Bot(session["token"])
            try:
                return await clear_test_webhook(bot, state)
            finally:
                await bot.session.close()
        try:
            if not asyncio.run(clear()):
                print("Webhook did not match this stand; it was left unchanged")
            else:
                credentials_can_clear = True
        except Exception:
            print("Could not verify test webhook removal; other webhooks were not touched")
    (root / "stop-server").write_text(state.get("session_id", ""), encoding="utf-8")
    for _ in range(40):
        if not owned_process(state.get("api")):
            break
        time.sleep(.25)
    for key in ("api", "api_launcher", "tunnel"):
        terminate_owned(state.get(key))
    if stop_database:
        stop_postgres(root, cfg)
    if session_path.exists() and credentials_can_clear:
        session_path.unlink()  # Our transient credential copy; bot.env is retained.
    write_json(root / "processes.json", {**state, "api": None, "api_launcher": None, "tunnel": None})
    print("Own stand stopped; test database, bot.env and backups retained")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "check", "start", "status", "stop", "_serve"))
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    root = checked_root()
    cfg = read_private_config(root)
    configure_logging(cfg)
    if args.mode == "_serve":
        asyncio.run(serve(root, cfg, args.offline))
        return
    with operation_lock(root):
        if args.mode == "prepare":
            state = read_state(root)
            if owned_process(state.get("api")) or owned_process(state.get("tunnel")):
                raise TestStandError("Stop the owned stand before rebuilding it")
            prepare(root, cfg)
            print(f"Prepared private stand. Fill locally: {root / 'bot.env'}")
        elif args.mode == "check":
            load_bot_config(root / "bot.env")
            print("Test bot file format is valid; no Telegram request was sent")
        elif args.mode == "start":
            start(root, cfg, args.offline)
        elif args.mode == "stop":
            stop(root, cfg)
        else:
            from telegram_test_pg import postgres_status
            state = read_state(root)
            print("API:", "running" if owned_process(state.get("api")) else "stopped")
            print("Tunnel:", "running" if owned_process(state.get("tunnel")) else "stopped")
            print("PostgreSQL:", "running" if postgres_status(root, cfg)["running"] else "stopped")
            print("Automatic reminders: disabled")
            if state.get("public_url"):
                print("Last test URL:", state["public_url"])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Operation interrupted; use stop to close the owned stand", file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        logging.getLogger("telegram-test").error("%s", error)
        raise SystemExit(1)
