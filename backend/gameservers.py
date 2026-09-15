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

import rcon
from steam import profiles

# Hours a server may sit EMPTY before it is shut down. The clock measures idle
# time, not uptime: a server with players on it is never reaped.
AUTO_STOP_HOURS = int(os.environ.get("GAMESERVER_IDLE_STOP_HOURS",
                      os.environ.get("GAMESERVER_AUTO_STOP_HOURS", "12")))
MAX_EXTEND_HOURS = int(os.environ.get("GAMESERVER_MAX_EXTEND_HOURS", "24"))
WARN_BEFORE_MIN = int(os.environ.get("GAMESERVER_WARN_BEFORE_MIN", "15"))
BASE_DIR = Path(os.environ.get("GAMESERVER_BASE_DIR", "/opt/gameservers"))
STEAMCMD = os.environ.get("STEAMCMD_PATH", "steamcmd")
STOP_GRACE_SECONDS = int(os.environ.get("GAMESERVER_STOP_GRACE", "30"))
# Longer than a plain stop: the engine has to finish writing the world.
SAVE_STOP_GRACE = int(os.environ.get("GAMESERVER_SAVE_STOP_GRACE", "120"))

# Where the servers actually run. Blank = same host as the backend. Set these to
# drive a separate x86_64 box (the "gameserver") while the backend lives
# elsewhere, e.g. on a Pi that could never run SteamCMD itself.
SSH_HOST = os.environ.get("GAMESERVER_SSH_HOST", "").strip()
SSH_USER = os.environ.get("GAMESERVER_SSH_USER", "steam").strip()
SSH_PORT = os.environ.get("GAMESERVER_SSH_PORT", "22").strip()
SSH_KEY = os.environ.get("GAMESERVER_SSH_KEY", "").strip()

# Windows-only servers (ARK: Survival Ascended, Space Engineers) run on Linux
# through a compatibility layer. Steam must also be told to fetch the Windows
# depots, since SteamCMD otherwise serves the host platform's build.
PROTON_PATH = os.environ.get("PROTON_PATH", "/opt/proton/proton")
WINE_PATH = os.environ.get("WINE_PATH", "wine")
STEAM_ROOT = os.environ.get("STEAM_COMPAT_CLIENT_INSTALL_PATH", "/opt/steam")


def remote() -> bool:
    """True when servers run on a different machine than the backend."""
    return bool(SSH_HOST)


def _ssh_argv() -> list[str]:
    argv = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ConnectTimeout=10", "-p", SSH_PORT]
    if SSH_KEY:
        argv += ["-i", SSH_KEY]
    return argv + [f"{SSH_USER}@{SSH_HOST}"]


async def run_shell(command: str, timeout: int = 900) -> tuple[int, str]:
    """Run a shell command on whichever host owns the game servers."""
    argv = (_ssh_argv() + [command]) if remote() else ["bash", "-lc", command]
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        return 124, f"timed out after {timeout}s"
    except FileNotFoundError as e:
        return 127, str(e)
    return proc.returncode, (out or b"").decode("utf-8", "replace")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------- deadlines ----
def initial_deadline(start: Optional[datetime] = None) -> datetime:
    """Kept for callers that still want a wall-clock cap from a start time."""
    return (start or now_utc()) + timedelta(hours=AUTO_STOP_HOURS)


def extended_deadline(hours: float, frm: Optional[datetime] = None) -> datetime:
    """Suppress idle shutdown until this time. Relative to now, and clamped."""
    hours = max(0.25, min(float(hours), MAX_EXTEND_HOURS))
    return (frm or now_utc()) + timedelta(hours=hours)


def _dt(value) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def occupancy_patch(rec: dict, players: Optional[int],
                    ref: Optional[datetime] = None) -> dict:
    """Fields to persist after a player-count poll.

    players > 0  -> occupied; the idle clock stops and resets.
    players == 0 -> empty; the idle clock starts (or keeps running).
    players None -> the server can't be queried. The count is left unknown and
                    the idle clock falls back to running from server start, so
                    an unqueryable server still shuts down eventually instead of
                    running forever.
    """
    ref = ref or now_utc()
    if players is None:
        patch = {"players_known": False}
        if not rec.get("empty_since"):
            patch["empty_since"] = (rec.get("started_at") or ref.isoformat())
        return patch
    if players > 0:
        return {"players_online": players, "players_known": True, "empty_since": None}
    patch = {"players_online": 0, "players_known": True}
    if not rec.get("empty_since"):
        patch["empty_since"] = ref.isoformat()
    return patch


def idle_seconds(rec: dict, ref: Optional[datetime] = None) -> Optional[float]:
    """How long the server has had nobody on it. None while occupied."""
    if rec.get("players_online"):
        return None
    since = _dt(rec.get("empty_since"))
    if not since:
        return None
    return ((ref or now_utc()) - since).total_seconds()


def remaining_seconds(rec: dict, ref: Optional[datetime] = None) -> Optional[float]:
    """Seconds until idle shutdown. None when it isn't on a clock at all."""
    if rec.get("keepalive"):
        return None
    grace = _dt(rec.get("idle_grace_until"))
    ref = ref or now_utc()
    if grace and grace > ref:
        return (grace - ref).total_seconds()
    idle = idle_seconds(rec, ref)
    if idle is None:
        return None
    return AUTO_STOP_HOURS * 3600 - idle


def is_due(rec: dict, ref: Optional[datetime] = None) -> bool:
    """Should the reaper stop this server now?"""
    if rec.get("status") != "running" or rec.get("keepalive"):
        return False
    if rec.get("players_online"):
        return False          # never shut down an occupied server
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


async def alive(rec: dict) -> bool:
    """Is this server's process still up, local or remote?"""
    pid = rec.get("pid")
    if not pid:
        return False
    if remote():
        code, _ = await run_shell(f"kill -0 {int(pid)} 2>/dev/null", timeout=20)
        return code == 0
    return is_alive(pid, rec.get("pid_start_ticks"))


async def _terminate_remote(pid: int, grace: int) -> str:
    """Same graceful stop, executed on the gameserver box."""
    code, _ = await run_shell(f"kill -0 {int(pid)} 2>/dev/null", timeout=20)
    if code != 0:
        return "already stopped"
    stop = (f"kill -TERM -{int(pid)} 2>/dev/null || kill -TERM {int(pid)} 2>/dev/null; "
            f"for i in $(seq 1 {int(grace)}); do kill -0 {int(pid)} 2>/dev/null || "
            f"{{ echo CLEAN; exit 0; }}; sleep 1; done; "
            f"kill -KILL -{int(pid)} 2>/dev/null || kill -KILL {int(pid)} 2>/dev/null; echo KILLED")
    _code, out = await run_shell(stop, timeout=grace + 30)
    return "stopped cleanly" if "CLEAN" in out else "force-killed after grace period"


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
    run_with = profiles.runner(rec)
    # Under Proton/Wine we launch the *Windows* binary even though the host is Linux.
    if run_with in ("proton", "wine"):
        binary = prof["windows"]
    else:
        binary = prof["linux"] if os.name != "nt" else prof["windows"]
    if not binary:
        return None

    d = install_dir(rec)
    args = prof["args"].format(
        dir=d, name=rec.get("name", "server"), port=rec.get("port") or prof["port"],
        password=rec.get("server_password") or "changeme",
        players=rec.get("max_players") or prof["players"],
    )
    exe = shlex.quote(str(d / binary))

    if run_with == "proton":
        prefix = shlex.quote(str(d / "compatdata"))
        return (f"STEAM_COMPAT_DATA_PATH={prefix} "
                f"STEAM_COMPAT_CLIENT_INSTALL_PATH={shlex.quote(STEAM_ROOT)} "
                f"{shlex.quote(PROTON_PATH)} run {exe} {args}").strip()
    if run_with == "wine":
        prefix = shlex.quote(str(d / "wineprefix"))
        return f"WINEPREFIX={prefix} {shlex.quote(WINE_PATH)} {exe} {args}".strip()
    return f"{exe} {args}".strip()


async def steamcmd_install(rec: dict, validate: bool = False) -> tuple[bool, str]:
    """Install or update the server's Steam app. Returns (ok, tail_of_output)."""
    d = install_dir(rec)
    d.mkdir(parents=True, exist_ok=True)
    # +@sSteamCmdForcePlatformType must precede +login to take effect.
    platform = ""
    if profiles.runner(rec) in ("proton", "wine"):
        platform = "+@sSteamCmdForcePlatformType windows "
    cmd = (f"mkdir -p {shlex.quote(str(d))} && {shlex.quote(STEAMCMD)} "
           f"{platform}+force_install_dir {shlex.quote(str(d))} +login anonymous "
           f"+app_update {int(rec['server_appid'])}{' validate' if validate else ''} +quit")
    code, out = await run_shell(cmd)
    if code == 127:
        where = f"{SSH_USER}@{SSH_HOST}" if remote() else "this host"
        return False, f"steamcmd not found on {where} (set STEAMCMD_PATH)"
    return code == 0, out[-1500:]


async def spawn(rec: dict) -> tuple[Optional[int], Optional[int], str]:
    """Launch the server. Returns (pid, start_ticks, message)."""
    cmd = build_launch(rec)
    if not cmd:
        return None, None, ("No launch profile for this game. Set launch_cmd on the "
                            "server to run it manually.")
    d = install_dir(rec)
    logs = d / "wp-server.log"
    # setsid detaches the server so it survives the SSH session / backend restart,
    # and puts it in its own process group so stopping it takes the children too.
    launch = (f"cd {shlex.quote(str(d))} 2>/dev/null || exit 66; "
              f"setsid nohup {cmd} >> {shlex.quote(str(logs))} 2>&1 < /dev/null & echo $!")
    code, out = await run_shell(launch, timeout=60)
    if code == 66:
        return None, None, f"Not installed yet ({d} missing) - install it first."
    if code != 0:
        return None, None, f"Could not start: {out.strip()[:300]}"
    pid = next((int(t) for t in out.split() if t.isdigit()), None)
    if not pid:
        return None, None, f"Started but no PID came back: {out.strip()[:200]}"

    await asyncio.sleep(2)
    if not await alive({"pid": pid}):
        return None, None, f"Server exited immediately; check {logs}"
    ticks = None if remote() else _proc_start_ticks(pid)
    return pid, ticks, f"Started (pid {pid})"


async def terminate(pid: int, grace: int = STOP_GRACE_SECONDS) -> str:
    """SIGTERM the process group, escalate to SIGKILL if it overstays `grace`."""
    if remote():
        return await _terminate_remote(pid, grace)
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


# ------------------------------------------------------------------ disks --
# `df` only reports mounted filesystems, so a brand-new unformatted disk is
# invisible to it. `lsblk` lists every block device, which is how an unused
# drive gets found.
LSBLK = "lsblk -b -P -o NAME,SIZE,TYPE,FSTYPE,LABEL,MOUNTPOINT,MODEL 2>/dev/null"
DF = "df -B1 --output=source,fstype,size,used,avail,pcent,target -x tmpfs -x devtmpfs 2>/dev/null"


def _parse_lsblk(out: str) -> list[dict]:
    """Parse `lsblk -P` key="value" pairs, one device per line."""
    devs = []
    for line in out.splitlines():
        if not line.strip():
            continue
        d = dict(re.findall(r'(\w+)="([^"]*)"', line))
        if not d.get("NAME"):
            continue
        try:
            size = int(d.get("SIZE") or 0)
        except ValueError:
            size = 0
        devs.append({
            "name": d["NAME"], "size_bytes": size, "type": d.get("TYPE", ""),
            "fstype": d.get("FSTYPE", ""), "label": d.get("LABEL", ""),
            "mountpoint": d.get("MOUNTPOINT", ""), "model": (d.get("MODEL") or "").strip(),
        })
    return devs


def _parse_df(out: str) -> list[dict]:
    rows = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 7:
            continue
        try:
            size, used, avail = int(parts[2]), int(parts[3]), int(parts[4])
        except ValueError:
            continue
        rows.append({"source": parts[0], "fstype": parts[1], "size_bytes": size,
                     "used_bytes": used, "avail_bytes": avail, "use_pct": parts[5],
                     "mount": " ".join(parts[6:])})
    return rows


def unused_disks(devices: list[dict]) -> list[dict]:
    """Whole disks with no filesystem and no mounted partition - free capacity."""
    out = []
    for d in devices:
        if d["type"] != "disk" or d["fstype"]:
            continue
        kids = [c for c in devices
                if c["name"] != d["name"] and c["name"].startswith(d["name"])]
        if any(c["fstype"] or c["mountpoint"] for c in kids):
            continue          # partitioned and in use
        out.append(d)
    return out


async def disk_report() -> dict:
    """Disks and free space on whichever host runs the game servers."""
    code_l, lsblk_out = await run_shell(LSBLK, timeout=30)
    code_d, df_out = await run_shell(DF, timeout=30)
    devices = _parse_lsblk(lsblk_out) if code_l == 0 else []
    filesystems = _parse_df(df_out) if code_d == 0 else []
    unused = unused_disks(devices)

    best = max(filesystems, key=lambda f: f["avail_bytes"], default=None)
    return {
        "host": f"{SSH_USER}@{SSH_HOST}" if remote() else "backend host",
        "remote": remote(),
        "devices": devices,
        "filesystems": filesystems,
        "unused_disks": unused,
        "largest_free_bytes": best["avail_bytes"] if best else 0,
        "largest_free_mount": best["mount"] if best else None,
        "install_root": str(BASE_DIR),
        "error": None if (code_l == 0 or code_d == 0) else (lsblk_out or df_out)[:300],
    }


def fits(report: dict, needed_bytes: int) -> tuple[bool, str]:
    """Does a planned install fit where servers actually get installed?"""
    root = str(BASE_DIR)
    target = None
    for f in sorted(report.get("filesystems", []), key=lambda x: -len(x["mount"])):
        if root == f["mount"] or root.startswith(f["mount"].rstrip("/") + "/"):
            target = f
            break
    if not target:
        return False, f"No filesystem found for {root}"
    avail = target["avail_bytes"]
    if avail >= needed_bytes:
        return True, (f"{human_bytes(needed_bytes)} needed, "
                      f"{human_bytes(avail)} free on {target['mount']}")
    short = needed_bytes - avail
    msg = (f"Not enough room: {human_bytes(needed_bytes)} needed, only "
           f"{human_bytes(avail)} free on {target['mount']} "
           f"(short {human_bytes(short)})")
    spare = report.get("unused_disks") or []
    if spare:
        biggest = max(spare, key=lambda d: d["size_bytes"])
        msg += (f". There is an unformatted {human_bytes(biggest['size_bytes'])} disk "
                f"(/dev/{biggest['name']}) that could be formatted and mounted at {root}")
    return False, msg


def human_bytes(n: int) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


# ------------------------------------------------------------ save/stop ----
async def save_world(rec: dict) -> tuple[bool, str]:
    """Ask the server to flush its world to disk, if it speaks RCON.

    Returns (attempted, message). A game with no RCON save is not a failure -
    its engine saves when SIGTERM arrives.
    """
    spec = profiles.save_command(rec)
    if not spec:
        return False, "no RCON save for this game; relying on save-on-exit"
    port, command = spec
    password = rec.get("rcon_password") or rec.get("server_password")
    if not password:
        return False, "no RCON password configured; relying on save-on-exit"
    host = SSH_HOST if remote() else "127.0.0.1"
    ok, msg = await rcon.save_world(host, port or 27020, password, command)
    return True, msg if ok else f"save failed ({msg}); stopping anyway"


async def save_then_stop(rec: dict, grace: int = None) -> str:
    """Save the world, then shut the server down cleanly.

    The grace period is deliberately generous: a large ARK or 7 Days world can
    take tens of seconds to flush, and killing mid-write is how saves corrupt.
    """
    attempted, save_msg = await save_world(rec)
    if grace is None:
        grace = SAVE_STOP_GRACE
    how = await terminate(rec["pid"], grace=grace)
    return f"{how} ({save_msg})" if attempted else how
