"""Game-server operations shared by the REST API and the Discord bot.

Both control surfaces go through here so the 12-hour rule, the audit trail, and
the status transitions behave identically no matter where a command came from.
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

import gameservers as gs
from steam import profiles

logger = logging.getLogger("webminpulse.gameservers")

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
    if rec.get("status") == "running" and not gs.is_alive(rec.get("pid"), rec.get("pid_start_ticks")):
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
        "warned_at": None, "last_message": msg}})
    await _audit(rec, "start", actor, f"pid={pid}")
    return True, (f"**{rec['name']}** is starting on port {rec.get('port')}.\n"
                  f"It will auto-stop in {gs.AUTO_STOP_HOURS}h "
                  f"— use `/extend {rec['name']}` to keep it up longer.")


async def stop(rec: dict, actor: str = "api", reason: str = "") -> tuple[bool, str]:
    rec = await reconcile(rec)
    if rec.get("status") != "running":
        return False, f"**{rec['name']}** is not running."
    await _db.gameservers.update_one({"id": rec["id"]}, {"$set": {"status": "stopping"}})
    how = await gs.terminate(rec["pid"])
    await _db.gameservers.update_one({"id": rec["id"]}, {"$set": {
        "status": "stopped", "pid": None, "auto_stop_at": None, "warned_at": None,
        "last_message": f"{how}{(' (' + reason + ')') if reason else ''}"}})
    await _audit(rec, "stop", actor, reason or how)
    return True, f"**{rec['name']}** stopped ({how})."


async def extend(rec: dict, hours: float, actor: str = "api") -> tuple[bool, str]:
    rec = await reconcile(rec)
    if rec.get("status") != "running":
        return False, f"**{rec['name']}** is not running, so there's nothing to extend."
    deadline = gs.extended_deadline(hours)
    await _db.gameservers.update_one({"id": rec["id"]}, {"$set": {
        "auto_stop_at": deadline.isoformat(), "warned_at": None}})
    await _audit(rec, "extend", actor, f"{hours}h")
    granted = gs.remaining_seconds({"auto_stop_at": deadline, "keepalive": False})
    return True, (f"**{rec['name']}** will now stay up for {gs.fmt_remaining(granted)} "
                  f"(max {gs.MAX_EXTEND_HOURS}h per extension).")


async def set_keepalive(rec: dict, on: bool, actor: str = "api") -> tuple[bool, str]:
    patch = {"keepalive": on}
    if not on and rec.get("status") == "running":
        # Coming off keepalive restarts the clock rather than stopping instantly.
        patch["auto_stop_at"] = gs.initial_deadline().isoformat()
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
