"""Owned portable PostgreSQL for the isolated Telegram test launcher.

No production defaults, services, Docker, reset command or data deletion. The
launcher supplies a private managed root and explicit generated credentials.
"""

from __future__ import annotations

import ctypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import socket
import subprocess
from urllib.parse import quote
from uuid import uuid4

import psycopg
from psycopg import sql


REPO = Path(__file__).resolve().parents[1]
_REPARSE = 0x400


def _no_reparse(path: Path) -> None:
    for candidate in (path, *path.parents):
        try:
            attributes = candidate.lstat()
        except FileNotFoundError:
            attributes = None
        if candidate.is_symlink() or (attributes is not None and getattr(attributes, "st_file_attributes", 0) & _REPARSE):
            raise RuntimeError("A managed PostgreSQL path contains a reparse point")
        if candidate == REPO:
            break


def _paths(root: Path, cfg: dict) -> tuple[Path, Path, Path]:
    root = Path(root).absolute()
    _no_reparse(root)
    root = root.resolve()
    venv = (REPO / ".venv").resolve()
    if root == venv or not root.is_relative_to(venv):
        raise RuntimeError("The Telegram PostgreSQL root must stay inside this workspace .venv")
    workspace = cfg.get("workspace")
    if not isinstance(workspace, str) or not workspace or not Path(workspace).is_absolute() or Path(workspace).resolve() != REPO:
        raise RuntimeError("The Telegram configuration belongs to a different workspace")
    identity = cfg.get("instance_id", "")
    if not isinstance(identity, str) or not re.fullmatch(r"[a-f0-9]{32}", identity):
        raise RuntimeError("The Telegram configuration has no valid instance identity")
    if cfg.get("db_name") != "gymbot_telegram" or cfg.get("db_user") != "gymbot_tg_test":
        raise RuntimeError("Only the isolated Telegram database and role are allowed")
    if not isinstance(cfg.get("pg_port"), int) or not 1024 <= cfg["pg_port"] <= 65535:
        raise RuntimeError("The Telegram PostgreSQL port is invalid")
    if not isinstance(cfg.get("db_password"), str) or not re.fullmatch(r"[a-f0-9]{48,128}", cfg["db_password"]):
        raise RuntimeError("The Telegram PostgreSQL password must be a generated private value")
    try:
        marker_path = root / ".managed.json"
        _no_reparse(marker_path)
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("The Telegram test root is not initialized") from exc
    if marker.get("workspace") != workspace or marker.get("instance_id") != identity:
        raise RuntimeError("The Telegram test root does not match this configuration")
    data = root / "postgres" / "data"
    binaries = REPO / ".venv" / "pg17" / "pgsql" / "bin"
    _no_reparse(data)
    _no_reparse(binaries)
    if not binaries.is_dir():
        raise RuntimeError("Portable PostgreSQL 17 is missing from this workspace")
    return root, data, binaries


def _cluster_marker(root: Path, data: Path, cfg: dict) -> None:
    try:
        marker_path = root / "postgres" / ".cluster.json"
        _no_reparse(marker_path)
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("Existing PostgreSQL data has no matching owned-cluster marker") from exc
    if (marker.get("instance_id") != cfg["instance_id"] or marker.get("workspace") != str(REPO)
            or marker.get("data") != str(data.resolve())):
        raise RuntimeError("Existing PostgreSQL data belongs to another test instance")


def _native_env(extra: dict | None = None) -> dict:
    # No ambient PGHOST, PGDATA, PGSERVICE, password file or connection URL.
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("PG")}
    if extra:
        env.update(extra)
    return env


def _native(root: Path, binary: Path, arguments: list[str], label: str, *, extra_env: dict | None = None,
            accepted: tuple[int, ...] = (0,), timeout: int = 60) -> int:
    _no_reparse(binary)
    if not binary.is_file():
        raise RuntimeError("A required portable PostgreSQL executable is missing")
    logs = root / "logs"
    _no_reparse(logs)
    logs.mkdir(exist_ok=True)
    stem = f"pg-{label}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}-{uuid4().hex[:8]}"
    # Physical files avoid waiting for inherited stdout pipe handles after
    # pg_ctl has detached the server on Windows.
    with (logs / f"{stem}.out.log").open("xb") as stdout, (logs / f"{stem}.err.log").open("xb") as stderr:
        try:
            result = subprocess.run([str(binary), *arguments], cwd=str(root), env=_native_env(extra_env),
                                    stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"Portable PostgreSQL operation {label} did not finish; inspect private logs") from exc
    if result.returncode not in accepted:
        raise RuntimeError(f"Portable PostgreSQL operation {label} failed; inspect private logs")
    return result.returncode


def ensure_cluster(root: Path, cfg: dict) -> None:
    root, data, binaries = _paths(root, cfg)
    if data.exists():
        _cluster_marker(root, data, cfg)
        for name in ("PG_VERSION", "global/pg_control", "postgresql.conf", "pg_hba.conf"):
            _no_reparse(data / name)
        if not (data / "PG_VERSION").is_file() or (data / "PG_VERSION").read_text(encoding="ascii").strip() != "17":
            raise RuntimeError("Existing test cluster is incomplete or is not PostgreSQL 17; it was preserved")
        if not all((data / name).is_file() for name in ("global/pg_control", "postgresql.conf", "pg_hba.conf")):
            raise RuntimeError("Existing test cluster is incomplete; no files were removed")
        return
    postgres_root = root / "postgres"
    _no_reparse(postgres_root)
    postgres_root.mkdir(exist_ok=True)
    marker_path = postgres_root / ".cluster.json"
    marker = {"workspace": str(REPO), "instance_id": cfg["instance_id"], "data": str(data.resolve())}
    if marker_path.exists():
        _cluster_marker(root, data, cfg)
    else:
        marker_path.write_text(json.dumps(marker), encoding="utf-8")
    password_path = postgres_root / f"initdb-password-{uuid4().hex}.txt"
    with password_path.open("x", encoding="utf-8", newline="\n") as output:
        output.write(cfg["db_password"] + "\n")
    try:
        _native(root, binaries / "initdb.exe", ["-D", str(data), "--username", cfg["db_user"],
                "--pwfile", str(password_path), "--auth-host=scram-sha-256", "--auth-local=scram-sha-256",
                "--encoding=UTF8", "--no-locale"], "initdb")
    finally:
        # Only this newly created duplicate of the private runtime password is
        # disposable. Configuration, cluster contents and backups stay intact.
        password_path.unlink(missing_ok=True)


def _matches_postgres_process(pid: int, executable: Path, started: int) -> bool:
    if os.name != "nt":
        return Path(f"/proc/{pid}/exe").resolve() == executable.resolve()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel.GetProcessTimes.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = ctypes.c_ulong(len(buffer))
        created, exited, system, user = (ctypes.c_ulonglong() for _ in range(4))
        if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return False
        if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(system), ctypes.byref(user)):
            return False
        created_unix = (created.value - 116444736000000000) / 10000000
        return Path(buffer.value).resolve() == executable.resolve() and abs(created_unix - started) < 10
    finally:
        kernel.CloseHandle(handle)


def postgres_status(root: Path, cfg: dict) -> dict:
    root, data, binaries = _paths(root, cfg)
    if not data.exists():
        return {"running": False}
    _cluster_marker(root, data, cfg)
    code = _native(root, binaries / "pg_ctl.exe", ["-D", str(data), "status"], "status", accepted=(0, 3))
    if code == 3:
        return {"running": False}
    try:
        _no_reparse(data / "postmaster.pid")
        lines = (data / "postmaster.pid").read_text(encoding="utf-8").splitlines()
        pid, started, port = int(lines[0]), int(lines[2]), int(lines[3])
        matches = (Path(lines[1]).resolve() == data.resolve() and port == cfg["pg_port"]
                   and lines[5].strip() == "127.0.0.1")
    except (OSError, ValueError, IndexError) as exc:
        raise RuntimeError("Running test PostgreSQL identity cannot be confirmed; nothing was stopped") from exc
    if not matches or not _matches_postgres_process(pid, binaries / "postgres.exe", started):
        raise RuntimeError("Running PostgreSQL does not match this isolated test cluster; nothing was stopped")
    return {"running": True}


def start_postgres(root: Path, cfg: dict) -> bool:
    root, data, binaries = _paths(root, cfg)
    ensure_cluster(root, cfg)
    if postgres_status(root, cfg)["running"]:
        return False
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", cfg["pg_port"])) == 0:
            raise RuntimeError("The test PostgreSQL port is occupied by another process")
    options = (f"-h 127.0.0.1 -p {cfg['pg_port']} -c log_statement=none "
               "-c log_min_error_statement=panic -c log_error_verbosity=terse "
               "-c log_parameter_max_length_on_error=0")
    _native(root, binaries / "pg_ctl.exe", ["-D", str(data), "-l", str(root / "logs" / "postgres-server.log"),
            "-o", options, "-w", "-t", "30", "start"], "start", timeout=45)
    if not postgres_status(root, cfg)["running"]:
        raise RuntimeError("Test PostgreSQL did not become ready")
    return True


def _connection(root: Path, cfg: dict, database: str):
    _, data, _ = _paths(root, cfg)
    if not postgres_status(root, cfg)["running"]:
        raise RuntimeError("The isolated PostgreSQL cluster is not running")
    connection = None
    try:
        connection = psycopg.connect(host="127.0.0.1", port=cfg["pg_port"], user=cfg["db_user"],
                                     password=cfg["db_password"], dbname=database, connect_timeout=5,
                                     options="", sslmode="disable", client_encoding="UTF8",
                                     application_name="gymbot-telegram-test", autocommit=True)
        reported = connection.execute("SHOW data_directory").fetchone()[0]
        if Path(reported).resolve() != data.resolve():
            connection.close()
            raise RuntimeError("Database connection belongs to another PostgreSQL cluster")
        return connection
    except psycopg.Error as exc:
        if connection is not None:
            connection.close()
        raise RuntimeError("Could not connect to the isolated PostgreSQL database") from exc


def ensure_database(root: Path, cfg: dict) -> None:
    with _connection(root, cfg, "postgres") as connection:
        if connection.execute("SELECT 1 FROM pg_database WHERE datname = %s", (cfg["db_name"],)).fetchone() is None:
            connection.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(cfg["db_name"])))


def database_url(cfg: dict) -> str:
    return (f"postgresql+psycopg://{quote(cfg['db_user'], safe='')}:{quote(cfg['db_password'], safe='')}"
            f"@127.0.0.1:{int(cfg['pg_port'])}/{quote(cfg['db_name'], safe='')}?connect_timeout=5")


def backup_database(root: Path, cfg: dict) -> Path:
    root, _, binaries = _paths(root, cfg)
    with _connection(root, cfg, cfg["db_name"]):
        pass
    backups = root / "backups"
    _no_reparse(backups)
    backups.mkdir(exist_ok=True)
    name = f"before-start-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}-{uuid4().hex[:8]}"
    partial, final = backups / f"{name}.partial", backups / f"{name}.dump"
    _native(root, binaries / "pg_dump.exe", ["--host", "127.0.0.1", "--port", str(cfg["pg_port"]),
            "--username", cfg["db_user"], "--dbname", cfg["db_name"], "--no-password", "--format=custom",
            "--file", str(partial)], "backup", extra_env={"PGPASSWORD": cfg["db_password"]})
    if final.exists() or not partial.is_file() or partial.stat().st_size == 0:
        raise RuntimeError("The private database backup could not be verified")
    partial.rename(final)
    return final


def stop_postgres(root: Path, cfg: dict) -> bool:
    root, data, binaries = _paths(root, cfg)
    if not postgres_status(root, cfg)["running"]:
        return False
    # A loopback port and process image alone are not sufficient if a stale PID
    # was recycled. Confirm the data directory using this instance's private
    # SCRAM credentials before asking pg_ctl to signal any process.
    with _connection(root, cfg, "postgres"):
        pass
    _native(root, binaries / "pg_ctl.exe", ["-D", str(data), "-m", "fast", "-w", "-t", "30", "stop"], "stop", timeout=45)
    return True
