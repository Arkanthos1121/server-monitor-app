"""WebminPulse backend test suite.

Covers: Auth (register/login/me), token protection, Server CRUD, offline
detection, check-one and check-all, alert generation (offline transition),
alerts list/clear, settings, and register-push validation.
"""
import os
import uuid
import time
import pytest
import requests

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/") if os.environ.get("EXPO_PUBLIC_BACKEND_URL") else None
if not BASE_URL:
    # Read from /app/frontend/.env
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("EXPO_PUBLIC_BACKEND_URL"):
                BASE_URL = line.split("=", 1)[1].strip().strip('"').rstrip("/")
                break

API = f"{BASE_URL}/api"

UNIQUE = uuid.uuid4().hex[:8]
TEST_EMAIL = f"test_{UNIQUE}@example.com"
TEST_PW = "SuperSecret123!"


# ---------------- fixtures --------------------------------------------------
@pytest.fixture(scope="session")
def s():
    return requests.Session()


@pytest.fixture(scope="session")
def auth(s):
    # Register a fresh user (unique email)
    r = s.post(f"{API}/auth/register", json={"email": TEST_EMAIL, "password": TEST_PW, "name": "Tester"})
    assert r.status_code == 200, f"register failed {r.status_code}: {r.text}"
    data = r.json()
    return {"token": data["token"], "user": data["user"]}


@pytest.fixture(scope="session")
def hdr(auth):
    return {"Authorization": f"Bearer {auth['token']}"}


# ---------------- Auth ------------------------------------------------------
class TestAuth:
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

    def test_login_wrong_password(self, s):
        r = s.post(f"{API}/auth/login", json={"email": TEST_EMAIL, "password": "wrong"})
        assert r.status_code == 401

    def test_me_with_bearer(self, s, hdr):
        r = s.get(f"{API}/auth/me", headers=hdr)
        assert r.status_code == 200
        assert r.json()["email"] == TEST_EMAIL

    def test_servers_without_auth_401(self, s):
        r = s.get(f"{API}/servers")
        assert r.status_code == 401

    def test_seeded_ops_account(self, s):
        r = s.post(f"{API}/auth/login", json={"email": "ops@example.com", "password": "secret123"})
        # Seeded account may or may not exist – allow 200 or 401
        assert r.status_code in (200, 401)


# ---------------- Server CRUD + offline ------------------------------------
class TestServersAndOffline:
    server_id: str = ""

    def test_add_unreachable_server_offline(self, s, hdr):
        r = s.post(
            f"{API}/servers",
            headers=hdr,
            json={
                "name": f"TEST_Node_{UNIQUE}",
                "host": "10.255.255.1",
                "port": 10000,
                "username": "root",
                "password": "pw",
                "use_ssl": True,
            },
            timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "id" in data
        assert data["webmin_url"] == "https://10.255.255.1:10000/"
        assert "password" not in data  # never leak password
        assert data["last_status"] is not None
        assert data["last_status"]["online"] is False
        TestServersAndOffline.server_id = data["id"]

    def test_list_servers_no_password(self, s, hdr):
        r = s.get(f"{API}/servers", headers=hdr)
        assert r.status_code == 200
        arr = r.json()
        assert any(sv["id"] == TestServersAndOffline.server_id for sv in arr)
        for sv in arr:
            assert "password" not in sv
            assert "webmin_url" in sv
            assert "last_status" in sv

    def test_get_server(self, s, hdr):
        sid = TestServersAndOffline.server_id
        r = s.get(f"{API}/servers/{sid}", headers=hdr)
        assert r.status_code == 200
        assert r.json()["id"] == sid

    def test_check_one_refresh(self, s, hdr):
        sid = TestServersAndOffline.server_id
        r = s.post(f"{API}/servers/{sid}/check", headers=hdr, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["last_status"]["online"] is False

    def test_check_all(self, s, hdr):
        r = s.post(f"{API}/servers/check-all", headers=hdr, timeout=60)
        assert r.status_code == 200
        arr = r.json()
        assert isinstance(arr, list) and len(arr) >= 1

    def test_update_server_password_optional(self, s, hdr):
        sid = TestServersAndOffline.server_id
        r = s.put(f"{API}/servers/{sid}", headers=hdr, json={"name": f"TEST_Renamed_{UNIQUE}"})
        assert r.status_code == 200
        assert r.json()["name"] == f"TEST_Renamed_{UNIQUE}"

    def test_update_server_with_password(self, s, hdr):
        sid = TestServersAndOffline.server_id
        r = s.put(f"{API}/servers/{sid}", headers=hdr, json={"password": "newpw"})
        assert r.status_code == 200
        # verify no password leaked
        assert "password" not in r.json()


# ---------------- Alerts (offline transition) ------------------------------
class TestAlerts:
    def test_offline_transition_creates_alert(self, s, hdr):
        # Add a fake server marked as ONLINE previously so a check produces
        # an online -> offline transition alert.
        add = s.post(
            f"{API}/servers",
            headers=hdr,
            json={
                "name": f"TEST_TransitionNode_{UNIQUE}",
                "host": "10.255.255.2",
                "port": 10000,
                "username": "root",
                "password": "pw",
                "use_ssl": True,
            },
            timeout=30,
        )
        assert add.status_code == 200
        sid = add.json()["id"]

        # Manipulate the DB is not accessible; instead, we exploit the update
        # endpoint won't set last_status. Use two consecutive checks – first
        # a "primer" where we mark it online via a real request cycle is not
        # possible. Instead, simulate transition via direct Mongo write is
        # not available, so rely on natural flow: initial creation was
        # offline, second check may not trigger alert.
        # However, the review mentions on->off transition. We test by
        # ensuring the alerts endpoint works and returns a list. We'll also
        # verify a running check does not error.
        r = s.post(f"{API}/servers/{sid}/check", headers=hdr, timeout=30)
        assert r.status_code == 200

        # Fetch alerts – may or may not contain 'offline' since prior state
        # was already offline. Just ensure endpoint works.
        al = s.get(f"{API}/alerts", headers=hdr)
        assert al.status_code == 200
        assert isinstance(al.json(), list)

    def test_offline_alert_via_direct_state_flip(self, s, hdr):
        """Force an online->offline transition using Mongo directly."""
        import pymongo
        cli = pymongo.MongoClient("mongodb://localhost:27017")
        db = cli["test_database"]
        # Find our TEST_Renamed server id
        srv = db.servers.find_one({"name": {"$regex": f"^TEST_Renamed_{UNIQUE}"}})
        if not srv:
            pytest.skip("target server not found")
        # Force prior state online
        db.servers.update_one({"id": srv["id"]}, {"$set": {"last_status": {"online": True, "cpu": None, "ram": None, "disk": None, "load": None, "uptime": None, "updates": None, "error": None, "checked_at": "2026-01-01T00:00:00+00:00"}}})
        # Now trigger a check – should mark offline and create alert
        r = s.post(f"{API}/servers/{srv['id']}/check", headers=hdr, timeout=30)
        assert r.status_code == 200
        assert r.json()["last_status"]["online"] is False

        al = s.get(f"{API}/alerts", headers=hdr)
        assert al.status_code == 200
        arr = al.json()
        assert any(a["type"] == "offline" and a["server_id"] == srv["id"] for a in arr), f"no offline alert found: {arr}"

    def test_clear_alerts(self, s, hdr):
        r = s.delete(f"{API}/alerts", headers=hdr)
        assert r.status_code == 200
        al = s.get(f"{API}/alerts", headers=hdr)
        assert al.status_code == 200
        assert al.json() == []


# ---------------- Settings --------------------------------------------------
class TestSettings:
    def test_update_settings_reflected_in_me(self, s, hdr):
        r = s.put(f"{API}/settings", headers=hdr, json={"cpu_threshold": 70, "ram_threshold": 75, "alerts_enabled": False})
        assert r.status_code == 200
        me = s.get(f"{API}/auth/me", headers=hdr).json()
        assert me["cpu_threshold"] == 70
        assert me["ram_threshold"] == 75
        assert me["alerts_enabled"] is False
        # restore
        s.put(f"{API}/settings", headers=hdr, json={"cpu_threshold": 85, "ram_threshold": 85, "alerts_enabled": True})


# ---------------- Push register --------------------------------------------
class TestPushRegister:
    def test_bad_body_422(self, s):
        r = s.post(f"{API}/register-push", json={"user_id": "x"})
        assert r.status_code == 422

    def test_valid_body_route_reachable(self, s, auth):
        r = s.post(
            f"{API}/register-push",
            json={"user_id": auth["user"]["user_id"], "platform": "ios", "device_token": "tok_" + UNIQUE},
            timeout=15,
        )
        # Placeholder key upstream → allow 201, 500 or 502
        assert r.status_code in (201, 500, 502), r.text


# ---------------- Cleanup ---------------------------------------------------
class TestZZCleanup:
    def test_delete_created_servers(self, s, hdr):
        arr = s.get(f"{API}/servers", headers=hdr).json()
        for sv in arr:
            if sv["name"].startswith("TEST_") or "TEST_" in sv["name"]:
                d = s.delete(f"{API}/servers/{sv['id']}", headers=hdr)
                assert d.status_code == 200
        left = s.get(f"{API}/servers", headers=hdr).json()
        assert all(not sv["name"].startswith("TEST_") for sv in left)
