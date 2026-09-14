import os
import re
import time
import uuid
import socket
import asyncio
import logging
import ipaddress
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, List

import jwt
import bcrypt
import httpx
from cryptography.fernet import Fernet
from fastapi import FastAPI, APIRouter, HTTPException, Header, Depends
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, EmailStr

import gameservers as gs
import gameserver_service as gsvc
import discord_bot
from steam import scanner as steam_scanner

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("webminpulse")

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

JWT_SECRET = os.environ["JWT_SECRET"]
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL_SECONDS", "1800"))
# Default per-user check cadence (minutes), seeded from POLL_INTERVAL_SECONDS so the
# self-host env knob actually takes effect for new accounts / users without a preference.
DEFAULT_POLL_MIN = max(1, POLL_INTERVAL // 60)
VALID_CHECK_MODES = ("webmin", "tcp", "ping")

# Encryption for stored Webmin passwords (at rest)
_fernet = Fernet(os.environ["SERVER_ENC_KEY"].encode())


def enc_secret(plain: str) -> str:
    return _fernet.encrypt(plain.encode()).decode()


def dec_secret(token: str) -> str:
    try:
        return _fernet.decrypt(token.encode()).decode()
    except Exception:
        # Legacy/plaintext fallback
        return token

# ---- Emergent push relay ---------------------------------------------------
PUSH_BASE_URL = "https://integrations.emergentagent.com"
PUSH_KEY = os.environ.get("EMERGENT_PUSH_KEY", "placeholder")
_push_client = httpx.AsyncClient(base_url=PUSH_BASE_URL, headers={"X-Push-Key": PUSH_KEY}, timeout=10.0)

EMERGENT_SESSION_URL = "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"

app = FastAPI()
api = APIRouter(prefix="/api")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


# =========================== Models =========================================
class SignupBody(BaseModel):
    email: EmailStr
    password: str
    name: Optional[str] = None


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class GoogleBody(BaseModel):
    session_id: str


class ServerBody(BaseModel):
    name: str
    host: str
    port: int = 10000
    username: str = "root"
    password: Optional[str] = None
    use_ssl: bool = True
    verify_cert: bool = False
    check_mode: str = "webmin"  # "webmin" | "tcp" | "ping"


class ServerUpdateBody(BaseModel):
    name: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    use_ssl: Optional[bool] = None
    verify_cert: Optional[bool] = None
    check_mode: Optional[str] = None
    alerts_enabled: Optional[bool] = None


class SettingsBody(BaseModel):
    cpu_threshold: Optional[int] = None
    ram_threshold: Optional[int] = None
    alerts_enabled: Optional[bool] = None
    poll_interval_minutes: Optional[int] = None


class RegisterPushBody(BaseModel):
    platform: str
    device_token: str
    user_id: Optional[str] = None  # ignored; kept for backward-compat, derived from token


class SteamScanBody(BaseModel):
    api_key: str
    steamid: str
    deep: bool = False


class GameServerBody(BaseModel):
    name: str
    game_appid: int
    game_name: str
    server_appid: Optional[int] = None
    port: Optional[int] = None
    max_players: Optional[int] = None
    launch_cmd: Optional[str] = None
    server_password: Optional[str] = None


class ExtendBody(BaseModel):
    hours: float = 6.0


class KeepaliveBody(BaseModel):
    on: bool = True


# =========================== Auth helpers ===================================
def hash_pw(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()


def verify_pw(p: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(p.encode(), h.encode())
    except Exception:
        return False


def make_jwt(user_id: str) -> str:
    payload = {"sub": user_id, "type": "email", "exp": now_utc() + timedelta(days=30)}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def public_user(u: dict) -> dict:
    return {
        "user_id": u["user_id"],
        "email": u.get("email"),
        "name": u.get("name"),
        "picture": u.get("picture"),
        "cpu_threshold": u.get("cpu_threshold", 85),
        "ram_threshold": u.get("ram_threshold", 85),
        "alerts_enabled": u.get("alerts_enabled", True),
        "poll_interval_minutes": u.get("poll_interval_minutes", DEFAULT_POLL_MIN),
    }


async def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.split(" ", 1)[1].strip()

    # Try JWT (email/password)
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        user = await db.users.find_one({"user_id": payload["sub"]}, {"_id": 0})
        if user:
            return user
    except Exception:
        pass

    # Try Google session token
    sess = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
    if sess:
        exp = sess.get("expires_at")
        if isinstance(exp, datetime):
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp > now_utc():
                user = await db.users.find_one({"user_id": sess["user_id"]}, {"_id": 0})
                if user:
                    return user
    raise HTTPException(status_code=401, detail="Invalid or expired token")


# =========================== Webmin client ==================================
def _to_float(v):
    try:
        if isinstance(v, list):
            v = v[0]
        return float(v)
    except Exception:
        return None


def _pct(used, total):
    u, t = _to_float(used), _to_float(total)
    if u is None or t is None or t == 0:
        return None
    return round(max(0.0, min(100.0, u / t * 100.0)), 1)


def _parse_stats(data: dict) -> dict:
    """Defensively parse Authentic-Theme stats.cgi?xhr-stats=general JSON."""
    out = {"cpu": None, "ram": None, "disk": None, "load": None, "uptime": None}
    try:
        cpu = data.get("cpu")
        if isinstance(cpu, list) and cpu:
            out["cpu"] = round(_to_float(cpu[0]) or 0.0, 1)
        elif cpu is not None:
            out["cpu"] = round(_to_float(cpu) or 0.0, 1)
    except Exception:
        pass
    try:
        mem = data.get("mem")
        if isinstance(mem, list) and len(mem) >= 2:
            # [total, free, ...] or [used, total]; detect by ordering
            a, b = _to_float(mem[0]), _to_float(mem[1])
            if a is not None and b is not None:
                # Authentic theme returns [total, free, swaptotal, swapfree]
                total, free = a, b
                if total >= free:
                    out["ram"] = _pct(total - free, total)
                else:
                    out["ram"] = _pct(a, b)
    except Exception:
        pass
    try:
        disk = data.get("disk")
        if isinstance(disk, list) and len(disk) >= 2:
            total, free = _to_float(disk[0]), _to_float(disk[1])
            if total and free is not None:
                out["disk"] = _pct(total - free, total)
    except Exception:
        pass
    try:
        load = data.get("load")
        if isinstance(load, list) and load:
            out["load"] = [_to_float(x) for x in load[:3]]
    except Exception:
        pass
    try:
        up = data.get("uptime") or data.get("uptimerec")
        if isinstance(up, dict):
            out["uptime"] = up.get("uptime") or up.get("string")
        elif up:
            out["uptime"] = str(up)
    except Exception:
        pass
    return out


# SSRF guard: block loopback, link-local (incl. 169.254.169.254 cloud metadata) and
# unspecified ranges. Private LAN (RFC1918) is intentionally ALLOWED — monitoring
# internal Webmin servers is the app's core purpose.
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("::/128"),
]


def _ip_is_blocked(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    # Normalize IPv4-mapped IPv6 (e.g. ::ffff:169.254.169.254) to its IPv4 form.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    # Block loopback, link-local (incl. cloud metadata 169.254.169.254), unspecified,
    # multicast and reserved. Private RFC1918 LANs remain allowed (core use case).
    if ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast or ip.is_reserved:
        return True
    return any(ip in net for net in _BLOCKED_NETWORKS)


def validate_host_allowed(host: str) -> None:
    """Raise 400 if the host resolves to a blocked (metadata/loopback/link-local) address."""
    candidates = set()
    try:
        candidates.add(str(ipaddress.ip_address(host)))
    except ValueError:
        try:
            for info in socket.getaddrinfo(host, None):
                candidates.add(info[4][0])
        except Exception:
            candidates = set()  # unresolvable now; will simply fail as offline later
    for ip in candidates:
        if _ip_is_blocked(ip):
            raise HTTPException(400, "Host is not allowed (loopback/link-local/metadata addresses are blocked).")


async def tcp_check(host: str, port: int, timeout: float = 5.0) -> bool:
    try:
        fut = asyncio.open_connection(host, port)
        reader, writer = await asyncio.wait_for(fut, timeout=timeout)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except Exception:
        return False


async def ping_check(host: str, timeout: int = 3) -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            "ping", "-c", "1", "-W", str(timeout), host,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        rc = await asyncio.wait_for(proc.wait(), timeout=timeout + 2)
        return rc == 0
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
        return False


async def check_server(srv: dict) -> dict:
    scheme = "https" if srv.get("use_ssl", True) else "http"
    host = srv["host"]
    port = srv["port"]
    base = f"{scheme}://{host}:{port}"
    auth = (srv.get("username") or "", dec_secret(srv.get("password") or ""))
    mode = srv.get("check_mode", "webmin")
    result = {
        "online": False,
        "cpu": None, "ram": None, "disk": None, "load": None, "uptime": None,
        "updates": None, "auth_ok": None, "error": None, "checked_at": now_utc().isoformat(),
    }
    # Defense in depth: skip fetching blocked targets (metadata/loopback/link-local).
    try:
        validate_host_allowed(host)
    except HTTPException:
        result["error"] = "blocked host"
        return result

    # Lightweight modes: TCP port open, or ICMP ping.
    if mode == "ping":
        result["online"] = await ping_check(host)
        if not result["online"]:
            result["error"] = "no ping reply"
        return result
    if mode == "tcp":
        result["online"] = await tcp_check(host, port)
        if not result["online"]:
            result["error"] = "port closed"
        return result

    try:
        async with httpx.AsyncClient(verify=srv.get("verify_cert", False), timeout=10.0, follow_redirects=False) as hc:
            # 1) Live stats (also proves reachability + auth)
            try:
                r = await hc.get(f"{base}/authentic-theme/stats.cgi?xhr-stats=general", auth=auth)
                result["online"] = True
                result["auth_ok"] = r.status_code != 401
                if r.status_code == 200:
                    try:
                        result.update(_parse_stats(r.json()))
                    except Exception:
                        pass
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout):
                result["error"] = "unreachable"
                return result

            # 1b) Fallback: modern Authentic Theme returns a websocket handle (not metrics)
            #     from stats.cgi, so scrape the Running Processes module for CPU/RAM/load.
            if result["cpu"] is None and result["ram"] is None:
                for path in ("/proc/index.cgi", "/proc/"):
                    try:
                        rp = await hc.get(f"{base}{path}", auth=auth)
                        if rp.status_code == 200:
                            parsed = _parse_proc_html(rp.text)
                            for k, v in parsed.items():
                                if v is not None and result.get(k) is None:
                                    result[k] = v
                            if parsed.get("cpu") is not None or parsed.get("ram") is not None:
                                break
                    except Exception:
                        pass

            # 2) Available package updates (best effort)
            try:
                ru = await hc.get(f"{base}/package-updates/", auth=auth)
                if ru.status_code == 200:
                    result["updates"] = _count_updates(ru.text)
            except Exception:
                pass
    except Exception:
        result["error"] = "check failed"
    return result


_UNIT_BYTES = {"b": 1, "kb": 1024, "kib": 1024, "mb": 1024**2, "mib": 1024**2,
               "gb": 1024**3, "gib": 1024**3, "tb": 1024**4, "tib": 1024**4}


def _to_bytes(num: str, unit: str):
    try:
        return float(num) * _UNIT_BYTES.get(unit.lower(), 1)
    except Exception:
        return None


def _parse_proc_html(html: str) -> dict:
    """Best-effort scrape of Webmin 'Running Processes' (proc) module for CPU/RAM/load."""
    out = {"cpu": None, "ram": None, "load": None}
    try:
        text = re.sub(r"<[^>]+>", " ", html)  # strip tags
        text = re.sub(r"\s+", " ", text)
        # Load averages: three floats after "load average(s)"
        m = re.search(r"load average[s]?.*?(\d+\.\d+).*?(\d+\.\d+).*?(\d+\.\d+)", text, re.I)
        if m:
            out["load"] = [float(m.group(1)), float(m.group(2)), float(m.group(3))]
        # CPU: "... N% idle" -> used = 100 - idle
        m = re.search(r"([\d.]+)\s*%\s*idle", text, re.I)
        if m:
            out["cpu"] = round(max(0.0, min(100.0, 100.0 - float(m.group(1)))), 1)
        # Real memory: "Real memory X UNIT total, Y UNIT used"
        m = re.search(r"[Rr]eal memory[^\d]*([\d.]+)\s*([KMGT]i?B)\s*total[^\d]*([\d.]+)\s*([KMGT]i?B)\s*used", text)
        if m:
            total = _to_bytes(m.group(1), m.group(2))
            used = _to_bytes(m.group(3), m.group(4))
            if total and used is not None and total > 0:
                out["ram"] = round(max(0.0, min(100.0, used / total * 100.0)), 1)
    except Exception:
        pass
    return out


def _count_updates(html: str) -> Optional[int]:
    try:
        m = re.search(r"(\d+)\s+package[s]?\s+can be updated", html, re.I)
        if m:
            return int(m.group(1))
        # Fallback: count rows in the updates table checkbox column
        rows = re.findall(r'name="?u"?\s+value', html)
        if rows:
            return len(rows)
        if re.search(r"no packages? (need|to be) updat", html, re.I) or re.search(r"All packages are up to date", html, re.I):
            return 0
    except Exception:
        return None
    return None


# =========================== Push helpers ===================================
async def register_push_upstream(body: dict):
    resp = await _push_client.post("/api/v1/push/users/register", json=body)
    if resp.status_code == 401:
        raise HTTPException(500, "EMERGENT_PUSH_KEY missing or invalid")
    if resp.status_code >= 500:
        raise HTTPException(502, "Push provider unavailable")
    resp.raise_for_status()
    return resp


async def send_push(recipients: List[str], data: dict, idempotency_key: Optional[str] = None):
    if not recipients:
        return
    if "title" not in data or "message" not in data:
        return
    payload = {"recipients": recipients[:100], "data": data}
    if idempotency_key:
        payload["$idempotency_key"] = idempotency_key
    resp = await _push_client.post("/api/v1/push/trigger", json=payload)
    if resp.status_code == 401:
        raise HTTPException(500, "EMERGENT_PUSH_KEY missing or invalid")
    if resp.status_code >= 500:
        raise HTTPException(502, "Push provider unavailable")
    resp.raise_for_status()


async def create_alert(user_id: str, server: dict, atype: str, message: str, severity: str, push: bool = True):
    alert = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "server_id": server["id"],
        "server_name": server["name"],
        "type": atype,
        "message": message,
        "severity": severity,
        "created_at": now_utc().isoformat(),
    }
    await db.alerts.insert_one(dict(alert))
    if push:
        try:
            await send_push(
                [user_id],
                {"title": f"{server['name']}", "message": message, "action_url": f"/server/{server['id']}"},
                idempotency_key=f"{server['id']}-{atype}-{int(now_utc().timestamp()) // 60}",
            )
        except Exception as e:
            logger.warning(f"push failed (non-blocking): {e}")


async def evaluate_and_alert(user: dict, server: dict, status: dict):
    """Compare new status to previous snapshot and raise alerts on transitions."""
    prev = server.get("last_status") or {}
    if not user.get("alerts_enabled", True) or not server.get("alerts_enabled", True):
        return
    cpu_t = user.get("cpu_threshold", 85)
    ram_t = user.get("ram_threshold", 85)

    # Offline / online transitions
    if prev.get("online") is True and status["online"] is False:
        await create_alert(user["user_id"], server, "offline", "Server is OFFLINE and unreachable.", "critical")
    elif prev.get("online") is False and status["online"] is True:
        await create_alert(user["user_id"], server, "online", "Server is back ONLINE.", "info")

    if status["online"]:
        cpu = status.get("cpu")
        if cpu is not None and cpu >= cpu_t and (prev.get("cpu") is None or prev.get("cpu") < cpu_t):
            await create_alert(user["user_id"], server, "cpu", f"CPU usage high: {cpu}% (>{cpu_t}%).", "warning")
        ram = status.get("ram")
        if ram is not None and ram >= ram_t and (prev.get("ram") is None or prev.get("ram") < ram_t):
            await create_alert(user["user_id"], server, "ram", f"RAM usage high: {ram}% (>{ram_t}%).", "warning")
        upd = status.get("updates")
        if upd and upd > 0 and upd > (prev.get("updates") or 0):
            await create_alert(user["user_id"], server, "updates", f"{upd} package update(s) available.", "info")


async def record_metric(server_id: str, status: dict):
    """Persist a telemetry sample for history/sparklines (online samples only)."""
    if not status.get("online"):
        return
    if status.get("cpu") is None and status.get("ram") is None:
        return
    try:
        await db.metrics.insert_one({
            "server_id": server_id,
            "ts": now_utc(),
            "cpu": status.get("cpu"),
            "ram": status.get("ram"),
            "disk": status.get("disk"),
        })
    except Exception as e:
        logger.warning(f"metric insert failed: {e}")


# =========================== Auth routes ====================================
# Lightweight in-memory brute-force throttle for login (per-email, per-process).
_login_attempts: dict = {}
_MAX_LOGIN_ATTEMPTS = 5
_LOGIN_WINDOW = 300  # seconds


def _check_login_rate(email: str):
    now = time.time()
    attempts = [t for t in _login_attempts.get(email, []) if now - t < _LOGIN_WINDOW]
    _login_attempts[email] = attempts
    if len(attempts) >= _MAX_LOGIN_ATTEMPTS:
        raise HTTPException(429, "Too many login attempts. Please wait a few minutes and try again.")


def _record_login_failure(email: str):
    _login_attempts.setdefault(email, []).append(time.time())


@api.post("/auth/register")
async def register(body: SignupBody):
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters long")
    existing = await db.users.find_one({"email": body.email.lower()})
    if existing:
        raise HTTPException(400, "An account with this email already exists")
    user = {
        "user_id": f"user_{uuid.uuid4().hex[:12]}",
        "email": body.email.lower(),
        "name": body.name or body.email.split("@")[0],
        "password_hash": hash_pw(body.password),
        "picture": None,
        "cpu_threshold": 85,
        "ram_threshold": 85,
        "alerts_enabled": True,
        "poll_interval_minutes": DEFAULT_POLL_MIN,
        "created_at": now_utc().isoformat(),
    }
    await db.users.insert_one(dict(user))
    return {"token": make_jwt(user["user_id"]), "user": public_user(user)}


@api.post("/auth/login")
async def login(body: LoginBody):
    email = body.email.lower()
    _check_login_rate(email)
    user = await db.users.find_one({"email": email}, {"_id": 0})
    if not user or not user.get("password_hash") or not verify_pw(body.password, user["password_hash"]):
        _record_login_failure(email)
        raise HTTPException(401, "Invalid email or password")
    _login_attempts.pop(email, None)
    return {"token": make_jwt(user["user_id"]), "user": public_user(user)}


@api.post("/auth/google")
async def google_login(body: GoogleBody):
    async with httpx.AsyncClient(timeout=10.0) as hc:
        resp = await hc.get(EMERGENT_SESSION_URL, headers={"X-Session-ID": body.session_id})
    if resp.status_code != 200:
        raise HTTPException(401, "Google authentication failed")
    d = resp.json()
    email = d["email"].lower()
    user = await db.users.find_one({"email": email}, {"_id": 0})
    if not user:
        user = {
            "user_id": f"user_{uuid.uuid4().hex[:12]}",
            "email": email,
            "name": d.get("name"),
            "picture": d.get("picture"),
            "password_hash": None,
            "cpu_threshold": 85,
            "ram_threshold": 85,
            "alerts_enabled": True,
            "poll_interval_minutes": DEFAULT_POLL_MIN,
            "created_at": now_utc().isoformat(),
        }
        await db.users.insert_one(dict(user))
    session_token = d["session_token"]
    await db.user_sessions.update_one(
        {"session_token": session_token},
        {"$set": {
            "session_token": session_token,
            "user_id": user["user_id"],
            "expires_at": now_utc() + timedelta(days=7),
            "created_at": now_utc(),
        }},
        upsert=True,
    )
    return {"token": session_token, "user": public_user(user)}


@api.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return public_user(user)


@api.put("/settings")
async def update_settings(body: SettingsBody, user: dict = Depends(get_current_user)):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if updates:
        await db.users.update_one({"user_id": user["user_id"]}, {"$set": updates})
    fresh = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0})
    return public_user(fresh)


# =========================== Server routes ==================================
def server_public(s: dict) -> dict:
    return {
        "id": s["id"],
        "name": s["name"],
        "host": s["host"],
        "port": s["port"],
        "username": s["username"],
        "use_ssl": s.get("use_ssl", True),
        "verify_cert": s.get("verify_cert", False),
        "check_mode": s.get("check_mode", "webmin"),
        "webmin_url": f"{'https' if s.get('use_ssl', True) else 'http'}://{s['host']}:{s['port']}/",
        "alerts_enabled": s.get("alerts_enabled", True),
        "last_status": s.get("last_status"),
        "created_at": s.get("created_at"),
    }


@api.post("/servers")
async def add_server(body: ServerBody, user: dict = Depends(get_current_user)):
    validate_host_allowed(body.host)
    if body.check_mode not in VALID_CHECK_MODES:
        raise HTTPException(400, f"check_mode must be one of {VALID_CHECK_MODES}")
    srv = {
        "id": str(uuid.uuid4()),
        "user_id": user["user_id"],
        "name": body.name,
        "host": body.host,
        "port": body.port,
        "username": body.username,
        "password": enc_secret(body.password or ""),
        "use_ssl": body.use_ssl,
        "verify_cert": body.verify_cert,
        "check_mode": body.check_mode,
        "alerts_enabled": True,
        "last_status": None,
        "created_at": now_utc().isoformat(),
    }
    status = await check_server(srv)
    srv["last_status"] = status
    await db.servers.insert_one(dict(srv))
    await record_metric(srv["id"], status)
    return server_public(srv)


@api.get("/servers")
async def list_servers(user: dict = Depends(get_current_user)):
    servers = await db.servers.find({"user_id": user["user_id"]}, {"_id": 0}).to_list(500)
    servers.sort(key=lambda s: s.get("created_at") or "")
    return [server_public(s) for s in servers]


@api.get("/servers/{server_id}")
async def get_server(server_id: str, user: dict = Depends(get_current_user)):
    srv = await db.servers.find_one({"id": server_id, "user_id": user["user_id"]}, {"_id": 0})
    if not srv:
        raise HTTPException(404, "Server not found")
    return server_public(srv)


@api.put("/servers/{server_id}")
async def update_server(server_id: str, body: ServerUpdateBody, user: dict = Depends(get_current_user)):
    srv = await db.servers.find_one({"id": server_id, "user_id": user["user_id"]}, {"_id": 0})
    if not srv:
        raise HTTPException(404, "Server not found")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if "host" in updates:
        validate_host_allowed(updates["host"])
    if "check_mode" in updates and updates["check_mode"] not in VALID_CHECK_MODES:
        raise HTTPException(400, f"check_mode must be one of {VALID_CHECK_MODES}")
    if "password" in updates:
        updates["password"] = enc_secret(updates["password"])
    if updates:
        await db.servers.update_one({"id": server_id}, {"$set": updates})
    # Re-check immediately so a corrected server reflects its new status right away.
    fresh = await db.servers.find_one({"id": server_id}, {"_id": 0})
    status = await check_server(fresh)
    await evaluate_and_alert(user, fresh, status)
    await record_metric(server_id, status)
    await db.servers.update_one({"id": server_id}, {"$set": {"last_status": status}})
    fresh = await db.servers.find_one({"id": server_id}, {"_id": 0})
    return server_public(fresh)


@api.delete("/servers/{server_id}")
async def delete_server(server_id: str, user: dict = Depends(get_current_user)):
    res = await db.servers.delete_one({"id": server_id, "user_id": user["user_id"]})
    if res.deleted_count == 0:
        raise HTTPException(404, "Server not found")
    await db.alerts.delete_many({"server_id": server_id})
    return {"status": "deleted"}


@api.post("/servers/{server_id}/check")
async def check_one(server_id: str, user: dict = Depends(get_current_user)):
    srv = await db.servers.find_one({"id": server_id, "user_id": user["user_id"]}, {"_id": 0})
    if not srv:
        raise HTTPException(404, "Server not found")
    status = await check_server(srv)
    await evaluate_and_alert(user, srv, status)
    await record_metric(server_id, status)
    await db.servers.update_one({"id": server_id}, {"$set": {"last_status": status}})
    fresh = await db.servers.find_one({"id": server_id}, {"_id": 0})
    return server_public(fresh)


@api.post("/servers/check-all")
async def check_all(user: dict = Depends(get_current_user)):
    servers = await db.servers.find({"user_id": user["user_id"]}, {"_id": 0}).to_list(500)
    sem = asyncio.Semaphore(10)

    async def _run(srv):
        async with sem:
            status = await check_server(srv)
            await evaluate_and_alert(user, srv, status)
            await record_metric(srv["id"], status)
            await db.servers.update_one({"id": srv["id"]}, {"$set": {"last_status": status}})

    await asyncio.gather(*[_run(s) for s in servers], return_exceptions=True)
    fresh = await db.servers.find({"user_id": user["user_id"]}, {"_id": 0}).to_list(500)
    fresh.sort(key=lambda s: s.get("created_at") or "")
    return [server_public(s) for s in fresh]


@api.get("/servers/{server_id}/history")
async def server_history(server_id: str, limit: int = 60, user: dict = Depends(get_current_user)):
    srv = await db.servers.find_one({"id": server_id, "user_id": user["user_id"]}, {"_id": 0})
    if not srv:
        raise HTTPException(404, "Server not found")
    limit = max(1, min(limit, 200))
    docs = await db.metrics.find({"server_id": server_id}, {"_id": 0}).sort("ts", -1).to_list(limit)
    docs.reverse()
    return [
        {
            "ts": d["ts"].isoformat() if isinstance(d.get("ts"), datetime) else d.get("ts"),
            "cpu": d.get("cpu"),
            "ram": d.get("ram"),
            "disk": d.get("disk"),
        }
        for d in docs
    ]


# =========================== Alerts routes ==================================
@api.get("/alerts")
async def list_alerts(user: dict = Depends(get_current_user)):
    alerts = await db.alerts.find({"user_id": user["user_id"]}, {"_id": 0}).to_list(500)
    alerts.sort(key=lambda a: a.get("created_at") or "", reverse=True)
    return alerts[:200]


@api.delete("/alerts")
async def clear_alerts(user: dict = Depends(get_current_user)):
    await db.alerts.delete_many({"user_id": user["user_id"]})
    return {"status": "cleared"}


# =========================== Push routes ====================================
@api.post("/register-push", status_code=201)
async def register_push(body: RegisterPushBody, user: dict = Depends(get_current_user)):
    payload = {"user_id": user["user_id"], "platform": body.platform, "device_token": body.device_token}
    await register_push_upstream(payload)
    return {"status": "registered"}


# =========================== Steam library ==================================
@api.post("/steam/scan")
async def steam_scan(body: SteamScanBody, user: dict = Depends(get_current_user)):
    """Scan a Steam library for games that can run a dedicated server."""
    try:
        catalog = steam_scanner.load_catalog()
        steamid = await asyncio.to_thread(steam_scanner.resolve_steamid, body.api_key, body.steamid)
        games = await asyncio.to_thread(steam_scanner.owned_games, body.api_key, steamid)
        report = await asyncio.to_thread(steam_scanner.scan, games, catalog, body.deep)
    except SystemExit as e:
        raise HTTPException(400, str(e))
    except Exception:
        raise HTTPException(502, "Could not reach Steam. Check the API key and try again.")

    await db.steam_scans.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"user_id": user["user_id"], "steamid": steamid,
                  "scanned_at": now_utc().isoformat(),
                  "total_games": report["total_games"],
                  "dedicated_capable": report["dedicated_capable"]}},
        upsert=True)
    return report


@api.get("/steam/scan")
async def steam_scan_cached(user: dict = Depends(get_current_user)):
    doc = await db.steam_scans.find_one({"user_id": user["user_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "No scan yet")
    return doc


# =========================== Game servers ===================================
@api.get("/gameservers")
async def list_gameservers(user: dict = Depends(get_current_user)):
    rows = [await gsvc.reconcile(r) for r in await gsvc.list_for_user(user["user_id"])]
    return [gsvc.public(r) for r in rows]


@api.post("/gameservers", status_code=201)
async def add_gameserver(body: GameServerBody, user: dict = Depends(get_current_user)):
    rec = await gsvc.create(
        user["user_id"], body.game_appid, body.game_name, body.server_appid,
        body.name, body.port, body.max_players, body.launch_cmd, body.server_password)
    return gsvc.public(rec)


async def _own_gameserver(server_id: str, user: dict) -> dict:
    rec = await db.gameservers.find_one(
        {"id": server_id, "user_id": user["user_id"]}, {"_id": 0})
    if not rec:
        raise HTTPException(404, "Game server not found")
    return rec


@api.post("/gameservers/{server_id}/start")
async def start_gameserver(server_id: str, user: dict = Depends(get_current_user)):
    ok, msg = await gsvc.start(await _own_gameserver(server_id, user), actor="app")
    if not ok:
        raise HTTPException(409, msg)
    return {"status": "starting", "message": msg}


@api.post("/gameservers/{server_id}/stop")
async def stop_gameserver(server_id: str, user: dict = Depends(get_current_user)):
    ok, msg = await gsvc.stop(await _own_gameserver(server_id, user), actor="app")
    if not ok:
        raise HTTPException(409, msg)
    return {"status": "stopped", "message": msg}


@api.post("/gameservers/{server_id}/extend")
async def extend_gameserver(server_id: str, body: ExtendBody,
                            user: dict = Depends(get_current_user)):
    ok, msg = await gsvc.extend(await _own_gameserver(server_id, user), body.hours, actor="app")
    if not ok:
        raise HTTPException(409, msg)
    return {"message": msg}


@api.post("/gameservers/{server_id}/keepalive")
async def keepalive_gameserver(server_id: str, body: KeepaliveBody,
                               user: dict = Depends(get_current_user)):
    ok, msg = await gsvc.set_keepalive(await _own_gameserver(server_id, user), body.on, actor="app")
    return {"message": msg}


@api.post("/gameservers/{server_id}/install")
async def install_gameserver(server_id: str, user: dict = Depends(get_current_user)):
    ok, msg = await gsvc.install(await _own_gameserver(server_id, user), actor="app")
    if not ok:
        raise HTTPException(502, msg)
    return {"message": msg}


@api.delete("/gameservers/{server_id}")
async def delete_gameserver(server_id: str, user: dict = Depends(get_current_user)):
    rec = await _own_gameserver(server_id, user)
    if rec.get("status") == "running":
        await gsvc.stop(rec, actor="app", reason="server deleted")
    await db.gameservers.delete_one({"id": server_id, "user_id": user["user_id"]})
    return {"status": "deleted"}


@api.get("/gameservers/disk")
async def gameserver_disk(user: dict = Depends(get_current_user)):
    """Disks and free space on the host that runs the game servers."""
    return await gs.disk_report()


# =========================== Auto-stop reaper ===============================
async def reaper_loop():
    """Enforce the auto-stop deadline and warn in Discord shortly beforehand."""
    await asyncio.sleep(15)
    while True:
        try:
            # Ask every running server how many people are on it. This drives
            # both the idle shutdown and the "don't stop an occupied server" guard.
            await gsvc.poll_all_occupancy()

            for rec in await gsvc.due_stop_requests():
                ok, msg = await gsvc.stop(rec, actor="stop-request",
                                          reason="requested stop, nobody objected",
                                          force=True)
                if ok:
                    await discord_bot.announce(
                        f"🛑 **{rec['name']}** stopped — nobody cancelled the request.")

            for rec in await gsvc.due_for_warning():
                rem = gs.fmt_remaining(gs.remaining_seconds(rec))
                await gsvc.mark_warned(rec)
                await discord_bot.announce(
                    f"⏳ **{rec['name']}** has been empty a while and stops in {rem}. "
                    f"Join it or use `/extend {rec['name']}` to keep it up.")
            for rec, _msg in await gsvc.reap():
                await discord_bot.announce(
                    f"🛑 **{rec['name']}** sat empty for {gs.AUTO_STOP_HOURS}h — "
                    f"world saved and shut down. `/start {rec['name']}` brings it back.")
        except Exception as e:
            logger.warning(f"reaper error: {e}")
        await asyncio.sleep(60)


# =========================== Background poller ===============================
async def poller_loop():
    await asyncio.sleep(20)
    sem = asyncio.Semaphore(10)

    async def _process(user: dict, srv: dict):
        async with sem:
            status = await check_server(srv)
            await evaluate_and_alert(user, srv, status)
            await record_metric(srv["id"], status)
            await db.servers.update_one({"id": srv["id"]}, {"$set": {"last_status": status}})

    while True:
        try:
            servers = await db.servers.find({}, {"_id": 0}).to_list(2000)
            users_cache: dict = {}
            due_pairs = []
            for srv in servers:
                uid = srv["user_id"]
                if uid not in users_cache:
                    users_cache[uid] = await db.users.find_one({"user_id": uid}, {"_id": 0})
                user = users_cache[uid]
                if not user:
                    continue
                interval_min = user.get("poll_interval_minutes", DEFAULT_POLL_MIN)
                last = (srv.get("last_status") or {}).get("checked_at")
                due = True
                if last:
                    try:
                        lt = datetime.fromisoformat(last)
                        if lt.tzinfo is None:
                            lt = lt.replace(tzinfo=timezone.utc)
                        due = (now_utc() - lt).total_seconds() >= interval_min * 60
                    except Exception:
                        due = True
                if due:
                    due_pairs.append((user, srv))
            if due_pairs:
                await asyncio.gather(*[_process(u, s) for u, s in due_pairs], return_exceptions=True)
            checked = len(due_pairs)
            if checked:
                logger.info(f"Poller cycle: {checked} servers checked")
        except Exception as e:
            logger.warning(f"poller error: {e}")
        # Wake up frequently; per-user interval is enforced per server above.
        await asyncio.sleep(60)


@app.on_event("startup")
async def startup():
    await db.users.create_index("email", unique=True)
    await db.users.create_index("user_id", unique=True)
    await db.user_sessions.create_index("session_token", unique=True)
    await db.servers.create_index("user_id")
    await db.alerts.create_index("user_id")
    await db.metrics.create_index("server_id")
    await db.metrics.create_index("ts", expireAfterSeconds=7 * 24 * 3600)
    await db.gameservers.create_index("user_id")
    await db.gameserver_events.create_index("server_id")
    await db.steam_scans.create_index("user_id", unique=True)
    gsvc.init(db)
    asyncio.create_task(poller_loop())
    asyncio.create_task(reaper_loop())
    if discord_bot.enabled():
        asyncio.create_task(discord_bot.run(db))
        logger.info("Discord bot enabled")
    logger.info("WebminPulse backend started")


@app.on_event("shutdown")
async def shutdown():
    client.close()
    await _push_client.aclose()


@api.get("/")
async def root():
    return {"service": "WebminPulse API", "status": "ok"}


app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
