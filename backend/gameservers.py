"""Install, run, and time-limit self-hosted game servers.

The 12-hour rule: a server started through here gets an `auto_stop_at` deadline
12 hours out. A reaper stops it when the deadline passes, unless someone has
extended it or pinned it with keepalive. Extending is always relative to *now*,
so "/extend 2" from Discord means two more hours from the moment you ask.
"""
from __future__ import annotations

import asyncio
import os
import re
import shlex
import signal
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from steam import profiles

AUTO_STOP_HOURS = int(os.environ.get("GAMESERVER_AUTO_STOP_HOURS", "12"))
MAX_EXTEND_HOURS = int(os.environ.get("GAMESERVER_MAX_EXTEND_HOURS", "24"))
WARN_BEFORE_MIN = int(os.environ.get("GAMESERVER_WARN_BEFORE_MIN", "15"))
BASE_DIR = Path(os.environ.get("GAMESERVER_BASE_DIR", "/opt/gameservers"))
STEAMCMD = os.environ.get("STEAMCMD_PATH", "steamcmd")
STOP_GRACE_SECONDS = int(os.environ.get("GAMESERVER_STOP_GRACE", "30"))


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------- deadlines ----
def initial_deadline(start: Optional[datetime] = None) -> datetime:
    return (start or now_utc()) + timedelta(hours=AUTO_STOP_HOURS)


def extended_deadline(hours: float, frm: Optional[datetime] = None) -> datetime:
    """Extend relative to now. Clamped so one command can't pin a box forever."""
    hours = max(0.25, min(float(hours), MAX_EXTEND_HOURS))
    return (frm or now_utc()) + timedelta(hours=hours)


def remaining_seconds(rec: dict, ref: Optional[datetime] = None) -> Optional[float]:
    """Seconds until auto-stop. None when pinned by keepalive or not running."""
    if rec.get("keepalive"):
        return None
    dl = rec.get("auto_stop_at")
    if not dl:
        return None
    if isinstance(dl, str):
        dl = datetime.fromisoformat(dl)
    if dl.tzinfo is None:
        dl = dl.replace(tzinfo=timezone.utc)
    return (dl - (ref or now_utc())).total_seconds()


def is_due(rec: dict, ref: Optional[datetime] = None) -> bool:
    if rec.get("status") != "running" or rec.get("keepalive"):
        return False
    rem = remaining_seconds(rec, ref)
    return rem is not None and rem <= 0


def fmt_remaining(seconds: Optional[float]) -> str:
    if seconds is None:
        return "no auto-stop"
    if seconds <= 0:
        return "stopping now"
    h, m = divmod(int(seconds) // 60, 60)
    return f"{h}h {m}m" if h else f"{m}m"


# --------------------------------------------------------------- processes --
def _proc_start_ticks(pid: int) -> Optional[int]:
    """Process start time from /proc, used to detect PID reuse across restarts."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        return int(stat.rsplit(")", 1)[1].split()[19])
    except Exception:
        return None


def is_alive(pid: Optional[int], start_ticks: Optional[int] = None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError, OSError):
        return False
    if start_ticks is not None:
        seen = _proc_start_ticks(pid)
        if seen is not None and seen != start_ticks:
            return False  # PID was recycled by an unrelated process
    return True


def install_dir(rec: dict) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", rec["name"].lower()).strip("-") or "server"
    return BASE_DIR / f"{slug}-{rec['server_appid']}"


def build_launch(rec: dict) -> Optional[str]:
    """Resolve the command line for a server record, or None if unknown."""
    if rec.get("launch_cmd"):
        return rec["launch_cmd"]
    prof = profiles.get(rec.get("server_appid"))
    if not prof:
        return None
    binary = prof["linux"] if os.name != "nt" else prof["windows"]
    if not binary:
        return None
    d = install_dir(rec)
    args = prof["args"].format(
        dir=d, name=rec.get("name", "server"), port=rec.get("port") or prof["port"],
        password=rec.get("server_password") or "changeme",
        players=rec.get("max_players") or prof["players"],
    )
    return f"{shlex.quote(str(d / binary))} {args}".strip()


async def steamcmd_install(rec: dict, validate: bool = False) -> tuple[bool, str]:
    """Install or update the server's Steam app. Returns (ok, tail_of_output)."""
    d = install_dir(rec)
    d.mkdir(parents=True, exist_ok=True)
    cmd = [STEAMCMD, "+force_install_dir", str(d), "+login", "anonymous",
           "+app_update", str(rec["server_appid"])]
    if validate:
        cmd.append("validate")
    cmd.append("+quit")
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        out, _ = await proc.communicate()
    except FileNotFoundError:
        return False, f"steamcmd not found at '{STEAMCMD}' (set STEAMCMD_PATH)"
    tail = (out or b"").decode("utf-8", "replace")[-1500:]
    return proc.returncode == 0, tail


async def spawn(rec: dict) -> tuple[Optional[int], Optional[int], str]:
    """Launch the server. Returns (pid, start_ticks, message)."""
    cmd = build_launch(rec)
    if not cmd:
        return None, None, ("No launch profile for this game. Set launch_cmd on the "
                            "server to run it manually.")
    d = install_dir(rec)
    if not d.exists():
        return None, None, f"Not installed yet ({d} missing) - install it first."
    logs = d / "wp-server.log"
    try:
        fh = open(logs, "ab", buffering=0)
        proc = await asyncio.create_subprocess_exec(
            *shlex.split(cmd), cwd=str(d), stdout=fh, stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.DEVNULL, start_new_session=True)
    except FileNotFoundError:
        return None, None, f"Server binary missing for '{rec['name']}' - reinstall it."
    except Exception as e:
        return None, None, f"Could not start: {e}"
    await asyncio.sleep(1.5)
    if proc.returncode is not None:
        return None, None, f"Server exited immediately (code {proc.returncode}); see {logs}"
    return proc.pid, _proc_start_ticks(proc.pid), f"Started (pid {proc.pid})"


async def terminate(pid: int, grace: int = STOP_GRACE_SECONDS) -> str:
    """SIGTERM the process group, escalate to SIGKILL if it overstays `grace`."""
    if not is_alive(pid):
        return "already stopped"
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except Exception:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            return "already stopped"
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if not is_alive(pid):
            return "stopped cleanly"
        await asyncio.sleep(0.5)
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except Exception:
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:
            pass
    return "force-killed after grace period"
