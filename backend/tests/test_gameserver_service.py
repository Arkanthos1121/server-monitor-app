"""End-to-end tests for the Discord/API control flow against a fake Mongo.

Covers the behaviour actually requested: a server started from Discord stops
itself after 12 hours unless somebody extends it first.
"""
import os
import sys
from datetime import timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gameservers as gs  # noqa: E402
import gameserver_service as svc  # noqa: E402


# ------------------------------------------------------------- fake mongo --
class FakeCollection:
    def __init__(self):
        self.docs = []

    def _match(self, d, q):
        return all(d.get(k) == v for k, v in q.items())

    async def insert_one(self, doc):
        self.docs.append(dict(doc))

    async def find_one(self, q, _proj=None, sort=None):
        hits = [d for d in self.docs if self._match(d, q)]
        return dict(hits[0]) if hits else None

    def find(self, q, _proj=None):
        docs = [dict(d) for d in self.docs if self._match(d, q)]

        class C:
            async def to_list(self, _n):
                return docs
        return C()

    async def update_one(self, q, update, upsert=False):
        for d in self.docs:
            if self._match(d, q):
                d.update(update.get("$set", {}))
                return
        if upsert:
            self.docs.append({**q, **update.get("$set", {})})

    async def delete_one(self, q):
        self.docs = [d for d in self.docs if not self._match(d, q)]

    async def create_index(self, *a, **k):
        return None


class FakeDB:
    def __init__(self):
        self._c = {}

    def __getattr__(self, name):
        return self._c.setdefault(name, FakeCollection())


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    svc.init(d)
    # Never touch real processes in tests.
    monkeypatch.setattr(gs, "spawn", _fake_spawn)
    monkeypatch.setattr(gs, "terminate", _fake_terminate)
    monkeypatch.setattr(gs, "is_alive", lambda pid, ticks=None: pid == 4242)
    return d


async def _fake_spawn(rec):
    return 4242, 99, "Started (pid 4242)"


async def _fake_terminate(pid, grace=30):
    return "stopped cleanly"


async def make(db, **kw):
    rec = await svc.create(user_id="u1", game_appid=892970, game_name="Valheim",
                           server_appid=896660, name=kw.pop("name", "valheim-main"))
    await db.gameservers.update_one({"id": rec["id"]}, {"$set": {"installed": True, **kw}})
    return await db.gameservers.find_one({"id": rec["id"]})


async def reload(db, rec):
    return await db.gameservers.find_one({"id": rec["id"]})


def shift(db, rec, **delta):
    """Rewind a server's deadline to simulate time passing."""
    dl = gs.now_utc() - timedelta(**delta)
    return db.gameservers.update_one({"id": rec["id"]}, {"$set": {"auto_stop_at": dl.isoformat()}})


# -------------------------------------------------------------- the flow ---
@pytest.mark.asyncio
async def test_start_sets_twelve_hour_deadline(db):
    rec = await make(db)
    ok, msg = await svc.start(rec, actor="discord:tester")
    assert ok and "auto-stop in 12h" in msg
    rec = await reload(db, rec)
    assert rec["status"] == "running" and rec["pid"] == 4242
    rem = gs.remaining_seconds(rec)
    assert 11.9 * 3600 < rem <= 12 * 3600


@pytest.mark.asyncio
async def test_cannot_start_twice(db):
    rec = await make(db)
    await svc.start(rec)
    ok, msg = await svc.start(await reload(db, rec))
    assert not ok and "already running" in msg


@pytest.mark.asyncio
async def test_cannot_start_uninstalled(db):
    rec = await make(db, installed=False)
    ok, msg = await svc.start(rec)
    assert not ok and "not installed" in msg


@pytest.mark.asyncio
async def test_reaper_stops_server_past_twelve_hours(db):
    rec = await make(db)
    await svc.start(rec)
    await shift(db, rec, minutes=1)          # deadline now in the past
    stopped = await svc.reap()
    assert len(stopped) == 1
    assert (await reload(db, rec))["status"] == "stopped"


@pytest.mark.asyncio
async def test_reaper_leaves_server_inside_window(db):
    rec = await make(db)
    await svc.start(rec)
    assert await svc.reap() == []
    assert (await reload(db, rec))["status"] == "running"


@pytest.mark.asyncio
async def test_extend_saves_a_server_from_the_reaper(db):
    """The requested escape hatch: extend before the limit and it stays up."""
    rec = await make(db)
    await svc.start(rec)
    await shift(db, rec, minutes=1)          # about to be reaped
    ok, msg = await svc.extend(await reload(db, rec), 3, actor="discord:tester")
    assert ok and ("2h 59m" in msg or "3h 0m" in msg)
    assert await svc.reap() == []
    assert (await reload(db, rec))["status"] == "running"


@pytest.mark.asyncio
async def test_keepalive_survives_the_reaper(db):
    rec = await make(db)
    await svc.start(rec)
    await svc.set_keepalive(await reload(db, rec), True)
    await shift(db, rec, hours=48)
    assert await svc.reap() == []
    assert (await reload(db, rec))["status"] == "running"


@pytest.mark.asyncio
async def test_keepalive_off_rearms_the_timer(db):
    rec = await make(db)
    await svc.start(rec)
    await svc.set_keepalive(await reload(db, rec), True)
    await svc.set_keepalive(await reload(db, rec), False)
    rem = gs.remaining_seconds(await reload(db, rec))
    assert 11.9 * 3600 < rem <= 12 * 3600


@pytest.mark.asyncio
async def test_extend_on_stopped_server_is_refused(db):
    rec = await make(db)
    ok, msg = await svc.extend(rec, 3)
    assert not ok and "not running" in msg


@pytest.mark.asyncio
async def test_warning_fires_once_inside_the_window(db):
    rec = await make(db)
    await svc.start(rec)
    await shift(db, rec, hours=-0.1)         # ~6 min of life left
    due = await svc.due_for_warning()
    assert len(due) == 1
    await svc.mark_warned(due[0])
    assert await svc.due_for_warning() == []


@pytest.mark.asyncio
async def test_dead_process_is_reconciled_to_stopped(db):
    """Backend restart or server crash must not leave a phantom 'running'."""
    rec = await make(db)
    await svc.start(rec)
    await db.gameservers.update_one({"id": rec["id"]}, {"$set": {"pid": 999999}})
    rec = await svc.reconcile(await reload(db, rec))
    assert rec["status"] == "stopped"
    assert "exited on its own" in rec["last_message"]


@pytest.mark.asyncio
async def test_stop_records_an_audit_trail(db):
    rec = await make(db)
    await svc.start(rec, actor="discord:alice")
    await svc.stop(await reload(db, rec), actor="discord:bob", reason="stopped from Discord")
    events = await db.gameserver_events.find({"server_id": rec["id"]}).to_list(50)
    actions = {e["action"]: e["actor"] for e in events}
    assert actions["start"] == "discord:alice"
    assert actions["stop"] == "discord:bob"


@pytest.mark.asyncio
async def test_find_resolves_by_name_and_partial(db):
    rec = await make(db, name="valheim-main")
    assert (await svc.find("u1", "valheim-main"))["id"] == rec["id"]
    assert (await svc.find("u1", "VALHEIM"))["id"] == rec["id"]
    assert (await svc.find("u1", "nope")) is None
