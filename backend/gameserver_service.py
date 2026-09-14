"""Game-server operations shared by the REST API and the Discord bot.

Both control surfaces go through here so the 12-hour rule, the audit trail, and
the status transitions behave identically no matter where a command came from.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Optional

import a2s
from datetime import timedelta

import gameservers as gs
from steam import profiles

logger = logging.getLogger("webminpulse.gameservers")

# How long people get to object before a requested stop goes through.
STOP_REQUEST_SECONDS = int(os.environ.get("GAMESERVER_STOP_NOTICE_SECONDS", "300"))

_db = None


def init(db):
    global _db
    _db = db


def public(rec: dict) -> dict:
    rem = gs.remaining_seconds(rec) if rec.get("status") == "running" else None
    return {
        "id": rec["id"], "name": rec["name"], "game_name": rec.get("game_name"),
        "game_appid": rec.get("game_appid"), "server_appid": rec.get("server_appid"),
        "status": rec.get("status", "stopped"), "port": rec.get("port"),
        "max_players": rec.get("max_players"), "installed": bool(rec.get("installed")),
        "keepalive": bool(rec.get("keepalive")),
        "started_at": rec.get("started_at"),
        "auto_stop_at": rec.get("auto_stop_at"),
        "auto_stop_in": gs.fmt_remaining(rem) if rec.get("status") == "running" else None,
        "players_online": rec.get("players_online"),
        "players_known": rec.get("players_known", False),
        "empty_since": rec.get("empty_since"),
        "pending_stop": rec.get("pending_stop"),
        "last_message": rec.get("last_message"),
    }


async def _audit(rec: dict, action: str, actor: str, detail: str = ""):
    await _db.gameserver_events.insert_one({
        "id": str(uuid.uuid4()), "server_id": rec["id"], "user_id": rec["user_id"],
        "action": action, "actor": actor, "detail": detail,
        "ts": gs.now_utc().isoformat(),
    })


async def list_for_user(user_id: str) -> list[dict]:
    rows = await _db.gameservers.find({"user_id": user_id}, {"_id": 0}).to_list(200)
    rows.sort(key=lambda r: r["name"].lower())
    return rows


async def find(user_id: str, needle: str) -> Optional[dict]:
    """Resolve a server by id, exact name, then unique prefix/substring."""
    needle = (needle or "").strip()
    if not needle:
        return None
    rows = await list_for_user(user_id)
    for r in rows:
        if r["id"] == needle or r["name"].lower() == needle.lower():
            return r
    part = [r for r in rows if needle.lower() in r["name"].lower()
            or needle.lower() in (r.get("game_name") or "").lower()]
    return part[0] if len(part) == 1 else None


async def reconcile(rec: dict) -> dict:
    """Trust the OS over the database: a dead PID means the server is stopped."""
    if rec.get("status") == "running" and not await gs.alive(rec):
        await _db.gameservers.update_one(
            {"id": rec["id"]},
            {"$set": {"status": "stopped", "pid": None, "auto_stop_at": None,
                      "last_message": "process exited on its own"}})
        rec = {**rec, "status": "stopped", "pid": None, "auto_stop_at": None,
               "last_message": "process exited on its own"}
    return rec


async def start(rec: dict, actor: str = "api") -> tuple[bool, str]:
    rec = await reconcile(rec)
    if rec.get("status") == "running":
        rem = gs.fmt_remaining(gs.remaining_seconds(rec))
        return False, f"**{rec['name']}** is already running (auto-stop in {rem})."
    if not rec.get("installed"):
        return False, f"**{rec['name']}** is not installed yet. Install it first."

    await _db.gameservers.update_one({"id": rec["id"]}, {"$set": {"status": "starting"}})
    pid, ticks, msg = await gs.spawn(rec)
    if not pid:
        await _db.gameservers.update_one(
            {"id": rec["id"]}, {"$set": {"status": "stopped", "last_message": msg}})
        await _audit(rec, "start_failed", actor, msg)
        return False, f"Could not start **{rec['name']}**: {msg}"

    started = gs.now_utc()
    deadline = gs.initial_deadline(started)
    await _db.gameservers.update_one({"id": rec["id"]}, {"$set": {
        "status": "running", "pid": pid, "pid_start_ticks": ticks,
        "started_at": started.isoformat(), "auto_stop_at": deadline.isoformat(),
        "warned_at": None, "last_message": msg,
        "players_online": 0, "players_known": False, "pending_stop": None,
        "idle_grace_until": None,
        # A freshly started server is empty; the idle clock starts now.
        "empty_since": started.isoformat()}})
    await _audit(rec, "start", actor, f"pid={pid}")
    return True, (f"**{rec['name']}** is starting on port {rec.get('port')}.\n"
                  f"It shuts down after {gs.AUTO_STOP_HOURS}h with nobody on it. "
                  f"Playing keeps it alive — no command needed.")


async def stop(rec: dict, actor: str = "api", reason: str = "",
               force: bool = False) -> tuple[bool, str]:
    """Stop a server, saving its world first.

    Refuses while people are playing unless forced - that guard is the whole
    anti-griefing mechanism, so it lives here rather than in one UI.
    """
    rec = await reconcile(rec)
    if rec.get("status") != "running":
        return False, f"**{rec['name']}** is not running."

    online = rec.get("players_online") or 0
    if online > 0 and not force:
        who = "1 person is" if online == 1 else f"{online} people are"
        return False, (f"{who} playing on **{rec['name']}** right now.\n"
                       f"Use `/requeststop {rec['name']}` to ask them to wrap up, "
                       f"or an admin can `/stop {rec['name']} force:True`.")

    await _db.gameservers.update_one({"id": rec["id"]}, {"$set": {"status": "stopping"}})
    how = await gs.save_then_stop(rec)
    await _db.gameservers.update_one({"id": rec["id"]}, {"$set": {
        "status": "stopped", "pid": None, "auto_stop_at": None, "warned_at": None,
        "players_online": 0, "empty_since": None, "pending_stop": None,
        "idle_grace_until": None,
        "last_message": f"{how}{(' (' + reason + ')') if reason else ''}"}})
    await _audit(rec, "force_stop" if (force and online) else "stop", actor,
                 reason or how)
    note = f" (forced past {online} online)" if (force and online) else ""
    return True, f"**{rec['name']}** stopped{note} — world saved. ({how})"


async def extend(rec: dict, hours: float, actor: str = "api") -> tuple[bool, str]:
    rec = await reconcile(rec)
    if rec.get("status") != "running":
        return False, f"**{rec['name']}** is not running, so there's nothing to extend."
    deadline = gs.extended_deadline(hours)
    await _db.gameservers.update_one({"id": rec["id"]}, {"$set": {
        "idle_grace_until": deadline.isoformat(),
        "auto_stop_at": deadline.isoformat(), "warned_at": None}})
    await _audit(rec, "extend", actor, f"{hours}h")
    granted = gs.remaining_seconds({"idle_grace_until": deadline, "keepalive": False})
    return True, (f"**{rec['name']}** will stay up for at least "
                  f"{gs.fmt_remaining(granted)} even while empty "
                  f"(max {gs.MAX_EXTEND_HOURS}h per extension).")


async def set_keepalive(rec: dict, on: bool, actor: str = "api") -> tuple[bool, str]:
    patch = {"keepalive": on}
    if not on and rec.get("status") == "running":
        # Coming off keepalive restarts the idle clock rather than stopping instantly.
        patch["empty_since"] = gs.now_utc().isoformat()
    await _db.gameservers.update_one({"id": rec["id"]}, {"$set": patch})
    await _audit(rec, "keepalive_on" if on else "keepalive_off", actor)
    if on:
        return True, f"**{rec['name']}** will not auto-stop until keepalive is turned off."
    return True, f"**{rec['name']}** is back on the {gs.AUTO_STOP_HOURS}h timer."


async def install(rec: dict, actor: str = "api") -> tuple[bool, str]:
    await _db.gameservers.update_one({"id": rec["id"]}, {"$set": {"status": "installing"}})
    ok, tail = await gs.steamcmd_install(rec)
    await _db.gameservers.update_one({"id": rec["id"]}, {"$set": {
        "status": "stopped", "installed": ok,
        "last_message": "installed" if ok else tail[-300:]}})
    await _audit(rec, "install", actor, "ok" if ok else tail[-300:])
    return (True, f"**{rec['name']}** installed and ready to start.") if ok else \
           (False, f"Install failed for **{rec['name']}**:\n```\n{tail[-600:]}\n```")


async def create(user_id: str, game_appid: int, game_name: str,
                 server_appid: Optional[int], name: str, port: Optional[int] = None,
                 max_players: Optional[int] = None, launch_cmd: Optional[str] = None,
                 server_password: Optional[str] = None) -> dict:
    prof = profiles.get(server_appid) or {}
    rec = {
        "id": str(uuid.uuid4()), "user_id": user_id, "name": name,
        "game_appid": int(game_appid), "game_name": game_name,
        "server_appid": int(server_appid) if server_appid else None,
        "port": port or prof.get("port"), "max_players": max_players or prof.get("players"),
        "launch_cmd": launch_cmd, "server_password": server_password,
        "status": "stopped", "installed": False, "keepalive": False,
        "pid": None, "pid_start_ticks": None, "started_at": None, "auto_stop_at": None,
        "warned_at": None, "last_message": None,
        "created_at": gs.now_utc().isoformat(),
    }
    await _db.gameservers.insert_one(dict(rec))
    return rec


async def due_for_warning() -> list[dict]:
    """Running servers inside the warning window that haven't been warned yet."""
    rows = await _db.gameservers.find({"status": "running"}, {"_id": 0}).to_list(500)
    out = []
    for r in rows:
        if r.get("keepalive") or r.get("warned_at"):
            continue
        rem = gs.remaining_seconds(r)
        if rem is not None and 0 < rem <= gs.WARN_BEFORE_MIN * 60:
            out.append(r)
    return out


async def mark_warned(rec: dict):
    await _db.gameservers.update_one(
        {"id": rec["id"]}, {"$set": {"warned_at": gs.now_utc().isoformat()}})


async def reap() -> list[tuple[dict, str]]:
    """Stop every running server whose 12-hour deadline has passed."""
    rows = await _db.gameservers.find({"status": "running"}, {"_id": 0}).to_list(500)
    stopped = []
    for r in rows:
        r = await reconcile(r)
        if gs.is_due(r):
            ok, msg = await stop(r, actor="auto-stop", reason=f"{gs.AUTO_STOP_HOURS}h limit reached")
            if ok:
                logger.info(f"auto-stopped {r['name']} ({gs.AUTO_STOP_HOURS}h limit)")
                stopped.append((r, msg))
    return stopped


# ----------------------------------------------------------- occupancy -----
async def poll_occupancy(rec: dict) -> dict:
    """Ask the server how many people are on it and persist the result."""
    port = profiles.query_port(rec)
    if not port:
        return rec
    host = gs.SSH_HOST if gs.remote() else "127.0.0.1"
    players = await a2s.player_count(host, port)
    patch = gs.occupancy_patch(rec, players)
    if patch:
        await _db.gameservers.update_one({"id": rec["id"]}, {"$set": patch})
        rec = {**rec, **patch}
    return rec


async def poll_all_occupancy() -> list[dict]:
    rows = await _db.gameservers.find({"status": "running"}, {"_id": 0}).to_list(500)
    out = []
    for r in rows:
        out.append(await poll_occupancy(await reconcile(r)))
    return out


# -------------------------------------------------- stop requests / veto ---
async def request_stop(rec: dict, actor: str, seconds: int = None) -> tuple[bool, str]:
    """Ask to stop an occupied server, giving the people on it a chance to object.

    This is the middle path between "anyone can kill your session" and "only
    admins can stop anything": the request is public, it waits, and any player
    can cancel it.
    """
    rec = await reconcile(rec)
    if rec.get("status") != "running":
        return False, f"**{rec['name']}** is not running."
    seconds = seconds or STOP_REQUEST_SECONDS
    if not rec.get("players_online"):
        ok, msg = await stop(rec, actor=actor, reason="empty at request time")
        return ok, msg
    if rec.get("pending_stop"):
        return False, f"A stop request for **{rec['name']}** is already running."

    due = gs.now_utc() + timedelta(seconds=seconds)
    pending = {"by": actor, "requested_at": gs.now_utc().isoformat(),
               "due_at": due.isoformat()}
    await _db.gameservers.update_one({"id": rec["id"]}, {"$set": {"pending_stop": pending}})
    await _audit(rec, "stop_requested", actor, f"{seconds}s notice")
    mins = max(1, seconds // 60)
    return True, (f"⏳ {actor} asked to stop **{rec['name']}** in {mins} min "
                  f"({rec['players_online']} online).\n"
                  f"Anyone on the server can cancel with `/keepplaying {rec['name']}`.")


async def cancel_stop(rec: dict, actor: str) -> tuple[bool, str]:
    rec = await reconcile(rec)
    if not rec.get("pending_stop"):
        return False, f"No stop request is pending for **{rec['name']}**."
    await _db.gameservers.update_one({"id": rec["id"]}, {"$set": {"pending_stop": None}})
    await _audit(rec, "stop_cancelled", actor)
    return True, f"✋ {actor} cancelled the stop request for **{rec['name']}**. Carry on."


async def due_stop_requests() -> list[dict]:
    """Stop requests whose notice period has elapsed."""
    rows = await _db.gameservers.find({"status": "running"}, {"_id": 0}).to_list(500)
    out = []
    for r in rows:
        pending = r.get("pending_stop")
        if not pending:
            continue
        due = gs._dt(pending.get("due_at"))
        if due and due <= gs.now_utc():
            out.append(r)
    return out
