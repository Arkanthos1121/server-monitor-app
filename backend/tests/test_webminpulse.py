"""WebminPulse backend test suite (iteration 2 — regression + new security).

Covers: auth (register/login/me + password >=8), login brute-force throttle,
Server CRUD (immediate check + no password leak), SSRF guard (block metadata/
loopback/unspecified; allow private LAN), offline detection, check-one/check-all,
alert offline-transition + clear, per-server alerts toggle, history endpoint,
settings, register-push auth-required.
"""
import os
import re
import uuid
import time
import pytest
import requests

# Read backend URL from frontend/.env (Kubernetes ingress → /api → backend)
_BASE = None
with open("/app/frontend/.env") as f:
    for line in f:
        if line.startswith("EXPO_PUBLIC_BACKEND_URL"):
            _BASE = line.split("=", 1)[1].strip().strip('"').rstrip("/")
            break
BASE_URL = _BASE
API = f"{BASE_URL}/api"

UNIQUE = uuid.uuid4().hex[:8]
TEST_EMAIL = f"test_{UNIQUE}@example.com"
TEST_PW = "SuperSecret123!"

MONGO_URL = None
DB_NAME = None
with open("/app/backend/.env") as f:
    for line in f:
        if line.startswith("MONGO_URL"):
            MONGO_URL = line.split("=", 1)[1].strip().strip('"')
        elif line.startswith("DB_NAME"):
            DB_NAME = line.split("=", 1)[1].strip().strip('"')


# ---------------- fixtures --------------------------------------------------
@pytest.fixture(scope="session")
def s():
    return requests.Session()


@pytest.fixture(scope="session")
def auth(s):
    r = s.post(f"{API}/auth/register", json={"email": TEST_EMAIL, "password": TEST_PW, "name": "Tester"})
    assert r.status_code == 200, f"register failed {r.status_code}: {r.text}"
    d = r.json()
    return {"token": d["token"], "user": d["user"]}


@pytest.fixture(scope="session")
def hdr(auth):
    return {"Authorization": f"Bearer {auth['token']}"}


# ---------------- Auth ------------------------------------------------------
class TestAuth:
    # Register: password < 8 chars must fail
    def test_register_short_password_400(self, s):
        r = s.post(f"{API}/auth/register",
                   json={"email": f"short_{UNIQUE}@example.com", "password": "abc", "name": "x"})
        assert r.status_code == 400, r.text

    def test_register_returns_token_and_user(self, auth):
        assert isinstance(auth["token"], str) and len(auth["token"]) > 20
        assert auth["user"]["email"] == TEST_EMAIL
        assert "user_id" in auth["user"]
        assert auth["user"].get("cpu_threshold") == 85

    def test_login_correct_password(self, s):
        r = s.post(f"{API}/auth/login", json={"email": TEST_EMAIL, "password": TEST_PW})
        assert r.status_code == 200
        d = r.json()
        assert "token" in d and d["user"]["email"] == TEST_EMAIL

    def test_login_wrong_password_401(self, s):
        r = s.post(f"{API}/auth/login", json={"email": TEST_EMAIL, "password": "wrong_pw"})
        assert r.status_code == 401

    def test_me_with_bearer(self, s, hdr):
        r = s.get(f"{API}/auth/me", headers=hdr)
        assert r.status_code == 200
        body = r.json()
        assert body["email"] == TEST_EMAIL
        for k in ("cpu_threshold", "ram_threshold", "alerts_enabled", "poll_interval_minutes"):
            assert k in body

    def test_servers_without_auth_401(self, s):
        r = s.get(f"{API}/servers")
        assert r.status_code == 401


# ---------------- Login brute-force throttle --------------------------------
class TestLoginThrottle:
    """5 wrong -> 401 each; 6th -> 429. A correct login before lockout resets."""

    def test_brute_force_returns_429_after_5_bad(self, s):
        email = f"bf_{UNIQUE}@example.com"
        # First create an account
        r = s.post(f"{API}/auth/register", json={"email": email, "password": "GoodPass123!"})
        assert r.status_code == 200

        # 5 failed attempts
        for i in range(5):
            r = s.post(f"{API}/auth/login", json={"email": email, "password": "bad"})
            assert r.status_code == 401, f"attempt {i}: {r.status_code} / {r.text}"
        # 6th should be 429 (rate limited)
        r = s.post(f"{API}/auth/login", json={"email": email, "password": "bad"})
        assert r.status_code == 429, f"expected 429 got {r.status_code}: {r.text}"

    def test_correct_login_resets_counter(self, s):
        email = f"bfok_{UNIQUE}@example.com"
        r = s.post(f"{API}/auth/register", json={"email": email, "password": "GoodPass123!"})
        assert r.status_code == 200
        # 2 bad
        for _ in range(2):
            r = s.post(f"{API}/auth/login", json={"email": email, "password": "bad"})
            assert r.status_code == 401
        # correct -> resets
        r = s.post(f"{API}/auth/login", json={"email": email, "password": "GoodPass123!"})
        assert r.status_code == 200
        # 5 more bad should be 401 (counter was reset)
        for i in range(5):
            r = s.post(f"{API}/auth/login", json={"email": email, "password": "bad"})
            assert r.status_code == 401, f"post-reset attempt {i}: {r.status_code}"


# ---------------- SSRF guard ------------------------------------------------
class TestSSRF:
    @pytest.mark.parametrize("host", ["169.254.169.254", "127.0.0.1", "0.0.0.0"])
    def test_blocked_hosts_400(self, s, hdr, host):
        r = s.post(f"{API}/servers", headers=hdr,
                   json={"name": f"TEST_ssrf_{host}", "host": host, "port": 10000,
                         "username": "root", "password": "pw", "use_ssl": True})
        assert r.status_code == 400, f"host {host}: {r.status_code} / {r.text}"

    @pytest.mark.parametrize("host", ["192.168.1.50", "10.255.255.1"])
    def test_private_lan_allowed(self, s, hdr, host):
        r = s.post(f"{API}/servers", headers=hdr,
                   json={"name": f"TEST_lan_{UNIQUE}_{host}", "host": host, "port": 10000,
                         "username": "root", "password": "pw", "use_ssl": True}, timeout=30)
        assert r.status_code == 200, f"host {host}: {r.status_code} / {r.text}"
        d = r.json()
        assert d["last_status"] is not None
        assert d["last_status"]["online"] is False  # unreachable
        # cleanup
        s.delete(f"{API}/servers/{d['id']}", headers=hdr)


# ---------------- Server CRUD + offline ------------------------------------
class TestServersAndOffline:
    server_id: str = ""

    def test_add_unreachable_server_offline(self, s, hdr):
        r = s.post(f"{API}/servers", headers=hdr,
                   json={"name": f"TEST_Node_{UNIQUE}", "host": "10.255.255.1", "port": 10000,
                         "username": "root", "password": "pw", "use_ssl": True, "verify_cert": False},
                   timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        # Expected fields
        for k in ("id", "name", "host", "port", "username", "use_ssl", "verify_cert",
                  "alerts_enabled", "webmin_url", "last_status", "created_at"):
            assert k in data, f"missing field {k}"
        assert "password" not in data
        assert data["webmin_url"] == "https://10.255.255.1:10000/"
        assert data["alerts_enabled"] is True
        assert data["verify_cert"] is False
        assert data["last_status"]["online"] is False
        TestServersAndOffline.server_id = data["id"]

    def test_list_servers_no_password(self, s, hdr):
        r = s.get(f"{API}/servers", headers=hdr)
        assert r.status_code == 200
        arr = r.json()
        assert any(sv["id"] == TestServersAndOffline.server_id for sv in arr)
        for sv in arr:
            assert "password" not in sv

    def test_get_server(self, s, hdr):
        sid = TestServersAndOffline.server_id
        r = s.get(f"{API}/servers/{sid}", headers=hdr)
        assert r.status_code == 200
        assert r.json()["id"] == sid

    def test_check_one_refresh(self, s, hdr):
        sid = TestServersAndOffline.server_id
        r = s.post(f"{API}/servers/{sid}/check", headers=hdr, timeout=30)
        assert r.status_code == 200
        assert r.json()["last_status"]["online"] is False

    def test_check_all(self, s, hdr):
        r = s.post(f"{API}/servers/check-all", headers=hdr, timeout=60)
        assert r.status_code == 200
        arr = r.json()
        assert isinstance(arr, list) and len(arr) >= 1

    def test_update_name_and_verify_cert(self, s, hdr):
        sid = TestServersAndOffline.server_id
        r = s.put(f"{API}/servers/{sid}", headers=hdr,
                  json={"name": f"TEST_Renamed_{UNIQUE}", "verify_cert": True, "alerts_enabled": False})
        assert r.status_code == 200
        d = r.json()
        assert d["name"] == f"TEST_Renamed_{UNIQUE}"
        assert d["verify_cert"] is True
        assert d["alerts_enabled"] is False
        # Persist check via GET
        g = s.get(f"{API}/servers/{sid}", headers=hdr).json()
        assert g["alerts_enabled"] is False and g["verify_cert"] is True

    def test_update_password_no_leak(self, s, hdr):
        sid = TestServersAndOffline.server_id
        r = s.put(f"{API}/servers/{sid}", headers=hdr, json={"password": "newpw123"})
        assert r.status_code == 200
        assert "password" not in r.json()

    def test_history_endpoint_returns_list(self, s, hdr):
        sid = TestServersAndOffline.server_id
        r = s.get(f"{API}/servers/{sid}/history", headers=hdr)
        assert r.status_code == 200
        assert isinstance(r.json(), list)  # empty is OK for never-online demo

    def test_reenable_alerts_for_transition_test(self, s, hdr):
        sid = TestServersAndOffline.server_id
        r = s.put(f"{API}/servers/{sid}", headers=hdr, json={"alerts_enabled": True})
        assert r.status_code == 200 and r.json()["alerts_enabled"] is True


# ---------------- Alerts (offline transition) ------------------------------
class TestAlerts:
    def test_offline_transition_creates_alert(self, s, hdr):
        """Force an online->offline transition via direct Mongo write."""
        try:
            import pymongo
        except ImportError:
            pytest.skip("pymongo not installed")
        cli = pymongo.MongoClient(MONGO_URL)
        db = cli[DB_NAME]
        sid = TestServersAndOffline.server_id
        assert sid, "server not created"
        # Force prior state online
        db.servers.update_one({"id": sid},
            {"$set": {"last_status": {"online": True, "cpu": 10, "ram": 20, "disk": None,
                                       "load": None, "uptime": None, "updates": None,
                                       "error": None, "checked_at": "2026-01-01T00:00:00+00:00"}}})
        # Trigger check -> should transition to offline + create alert
        r = s.post(f"{API}/servers/{sid}/check", headers=hdr, timeout=30)
        assert r.status_code == 200
        assert r.json()["last_status"]["online"] is False

        al = s.get(f"{API}/alerts", headers=hdr)
        assert al.status_code == 200
        arr = al.json()
        assert any(a["type"] == "offline" and a["server_id"] == sid for a in arr), \
            f"no offline alert: {arr}"

    def test_clear_alerts(self, s, hdr):
        r = s.delete(f"{API}/alerts", headers=hdr)
        assert r.status_code == 200
        al = s.get(f"{API}/alerts", headers=hdr).json()
        assert al == []


# ---------------- Settings --------------------------------------------------
class TestSettings:
    def test_update_settings_reflected_in_me(self, s, hdr):
        r = s.put(f"{API}/settings", headers=hdr,
                  json={"cpu_threshold": 70, "ram_threshold": 75,
                        "alerts_enabled": False, "poll_interval_minutes": 15})
        assert r.status_code == 200
        me = s.get(f"{API}/auth/me", headers=hdr).json()
        assert me["cpu_threshold"] == 70
        assert me["ram_threshold"] == 75
        assert me["alerts_enabled"] is False
        assert me["poll_interval_minutes"] == 15
        # Restore
        s.put(f"{API}/settings", headers=hdr,
              json={"cpu_threshold": 85, "ram_threshold": 85,
                    "alerts_enabled": True, "poll_interval_minutes": 30})


# ---------------- register-push auth required -------------------------------
class TestPushRegister:
    def test_no_token_401(self, s):
        r = s.post(f"{API}/register-push",
                   json={"platform": "ios", "device_token": "tok_" + UNIQUE})
        assert r.status_code == 401, r.text

    def test_with_token_reachable(self, s, hdr):
        r = s.post(f"{API}/register-push", headers=hdr,
                   json={"platform": "ios", "device_token": "tok_" + UNIQUE}, timeout=15)
        # Placeholder push key -> 500/502 acceptable; 201 if provider ok
        assert r.status_code in (201, 500, 502), r.text


# ---------------- Cleanup ---------------------------------------------------
class TestZZCleanup:
    def test_delete_created_servers(self, s, hdr):
        arr = s.get(f"{API}/servers", headers=hdr).json()
        for sv in arr:
            if "TEST_" in sv["name"]:
                d = s.delete(f"{API}/servers/{sv['id']}", headers=hdr)
                assert d.status_code == 200
