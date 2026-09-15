"""End-to-end tests for the Discord/API control flow against a fake Mongo.

Covers the behaviour actually requested: a server started from Discord stops
itself after 12 hours unless somebody extends it first.
"""
import os
import sys
from datetime import timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import a2s  # noqa: E402
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
    monkeypatch.setattr(gs, "save_then_stop", _fake_save_then_stop)
    # The live re-query in stop() must not touch a real socket; echo the row.
    monkeypatch.setattr(svc, "poll_occupancy", _echo_occupancy)
    monkeypatch.setattr(gs, "alive", _fake_alive)
    monkeypatch.setattr(gs, "is_alive", lambda pid, ticks=None: pid == 4242)
    return d


async def _fake_spawn(rec):
    return 4242, 99, "Started (pid 4242)"


async def _fake_terminate(pid, grace=30):
    return "stopped cleanly"


async def _echo_occupancy(rec):
    return rec


async def _fake_save_then_stop(rec, grace=None):
    saved.append(rec["id"])
    return "stopped cleanly (world saved)"


saved: list = []


async def _fake_alive(rec):
    """Only the PID our fake spawn hands out is considered a live process."""
    return rec.get("pid") == 4242


JEFF = "discord:Jeff"
ADMIN = "discord:Admin"


async def make(db, **kw):
    rec = await svc.create(user_id="u1", game_appid=892970, game_name="Valheim",
                           server_appid=896660, name=kw.pop("name", "valheim-main"))
    await db.gameservers.update_one({"id": rec["id"]}, {"$set": {"installed": True, **kw}})
    return await db.gameservers.find_one({"id": rec["id"]})


async def reload(db, rec):
    return await db.gameservers.find_one({"id": rec["id"]})


def idle_for(db, rec, **delta):
    """Backdate empty_since to simulate the server sitting empty that long."""
    when = gs.now_utc() - timedelta(**delta)
    return db.gameservers.update_one(
        {"id": rec["id"]},
        {"$set": {"empty_since": when.isoformat(), "players_online": 0,
                  "players_known": True}})


def occupy(db, rec, players=2):
    return db.gameservers.update_one(
        {"id": rec["id"]},
        {"$set": {"players_online": players, "players_known": True,
                  "empty_since": None}})


# -------------------------------------------------------------- the flow ---
@pytest.mark.asyncio
async def test_start_begins_the_idle_clock(db):
    rec = await make(db)
    ok, msg = await svc.start(rec, actor="discord:tester")
    assert ok and "12h with nobody on it" in msg
    rec = await reload(db, rec)
    assert rec["status"] == "running" and rec["pid"] == 4242
    assert rec["empty_since"] and rec["players_online"] == 0
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
async def test_reaper_stops_a_server_idle_for_twelve_hours(db):
    rec = await make(db)
    await svc.start(rec)
    await idle_for(db, rec, hours=12, minutes=1)
    stopped = await svc.reap()
    assert len(stopped) == 1
    assert (await reload(db, rec))["status"] == "stopped"


@pytest.mark.asyncio
async def test_reaper_leaves_an_occupied_server_alone_forever(db):
    """A server that has run for days with people on it must not be reaped."""
    rec = await make(db)
    await svc.start(rec)
    await occupy(db, rec, players=3)
    await db.gameservers.update_one(
        {"id": rec["id"]},
        {"$set": {"started_at": (gs.now_utc() - timedelta(days=4)).isoformat()}})
    assert await svc.reap() == []
    assert (await reload(db, rec))["status"] == "running"


@pytest.mark.asyncio
async def test_reaper_leaves_server_inside_window(db):
    rec = await make(db)
    await svc.start(rec)
    assert await svc.reap() == []
    assert (await reload(db, rec))["status"] == "running"


@pytest.mark.asyncio
async def test_extend_saves_a_server_from_the_reaper(db):
    """The escape hatch: extend before the limit and it stays up."""
    rec = await make(db)
    await svc.start(rec)
    await idle_for(db, rec, hours=12, minutes=1)   # about to be reaped
    ok, msg = await svc.extend(await reload(db, rec), 3, actor="discord:tester")
    assert ok and ("2h 59m" in msg or "3h 0m" in msg)
    assert await svc.reap() == []
    assert (await reload(db, rec))["status"] == "running"


@pytest.mark.asyncio
async def test_keepalive_survives_the_reaper(db):
    rec = await make(db)
    await svc.start(rec)
    await svc.set_keepalive(await reload(db, rec), True)
    await idle_for(db, rec, hours=48)
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
    await idle_for(db, rec, hours=11, minutes=54)   # ~6 min of idle left
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
    await svc.stop(await reload(db, rec), actor="discord:bob",
                   reason="stopped from Discord", is_admin=True)
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


# ------------------------------------------- griefing protection -----------
@pytest.mark.asyncio
async def test_cannot_stop_a_server_someone_is_playing_on(db):
    """The core protection: a friend cannot kill your session out from under you."""
    rec = await make(db)
    await svc.start(rec)
    await occupy(db, rec, players=2)
    ok, msg = await svc.stop(await reload(db, rec), actor="discord:griefer")
    assert not ok
    assert "2 people are playing" in msg
    assert "requeststop" in msg
    assert (await reload(db, rec))["status"] == "running"


@pytest.mark.asyncio
async def test_singular_wording_for_one_player(db):
    rec = await make(db)
    await svc.start(rec)
    await occupy(db, rec, players=1)
    _ok, msg = await svc.stop(await reload(db, rec), actor="discord:griefer")
    assert "1 person is playing" in msg


@pytest.mark.asyncio
async def test_empty_server_stops_with_no_friction(db):
    """Swapping ASA out for Space Engineers must stay a one-command action."""
    rec = await make(db)
    await svc.start(rec, actor=JEFF)
    ok, msg = await svc.stop(await reload(db, rec), actor=JEFF)
    assert ok and "world saved" in msg.lower()
    assert (await reload(db, rec))["status"] == "stopped"


@pytest.mark.asyncio
async def test_admin_can_force_past_players(db):
    rec = await make(db)
    await svc.start(rec)
    await occupy(db, rec, players=3)
    ok, msg = await svc.stop(await reload(db, rec), actor=ADMIN,
                             force=True, is_admin=True)
    assert ok and "forced past 3 online" in msg
    assert (await reload(db, rec))["status"] == "stopped"


@pytest.mark.asyncio
async def test_forcing_is_recorded_separately_in_the_audit_log(db):
    """A force-stop should be attributable, so griefing has a name on it."""
    rec = await make(db)
    await svc.start(rec)
    await occupy(db, rec, players=3)
    await svc.stop(await reload(db, rec), actor=ADMIN, force=True, is_admin=True)
    events = await db.gameserver_events.find({"server_id": rec["id"]}).to_list(50)
    forced = [e for e in events if e["action"] == "force_stop"]
    assert len(forced) == 1 and forced[0]["actor"] == ADMIN


@pytest.mark.asyncio
async def test_request_stop_gives_players_notice(db):
    rec = await make(db)
    await svc.start(rec)
    await occupy(db, rec, players=2)
    ok, msg = await svc.request_stop(await reload(db, rec), actor="discord:jeff")
    assert ok and "keepplaying" in msg
    pending = (await reload(db, rec))["pending_stop"]
    assert pending["by"] == "discord:jeff"
    assert (await reload(db, rec))["status"] == "running"


@pytest.mark.asyncio
async def test_a_player_can_veto_the_stop_request(db):
    rec = await make(db)
    await svc.start(rec)
    await occupy(db, rec, players=2)
    await svc.request_stop(await reload(db, rec), actor="discord:jeff")
    ok, msg = await svc.cancel_stop(await reload(db, rec), actor="discord:friend")
    assert ok and "cancelled" in msg
    assert (await reload(db, rec))["pending_stop"] is None
    assert await svc.due_stop_requests() == []


@pytest.mark.asyncio
async def test_request_on_an_empty_server_stops_it_immediately(db):
    rec = await make(db)
    await svc.start(rec, actor=JEFF)
    ok, msg = await svc.request_stop(await reload(db, rec), actor=JEFF)
    assert ok
    assert (await reload(db, rec))["status"] == "stopped"


@pytest.mark.asyncio
async def test_stop_request_comes_due_after_the_notice_period(db):
    rec = await make(db)
    await svc.start(rec)
    await occupy(db, rec, players=2)
    await svc.request_stop(await reload(db, rec), actor="discord:jeff", seconds=300)
    assert await svc.due_stop_requests() == []          # not yet
    past = (gs.now_utc() - timedelta(seconds=1)).isoformat()
    cur = await reload(db, rec)
    await db.gameservers.update_one(
        {"id": rec["id"]},
        {"$set": {"pending_stop": {**cur["pending_stop"], "due_at": past}}})
    due = await svc.due_stop_requests()
    assert len(due) == 1


@pytest.mark.asyncio
async def test_duplicate_stop_requests_are_refused(db):
    rec = await make(db)
    await svc.start(rec)
    await occupy(db, rec, players=2)
    await svc.request_stop(await reload(db, rec), actor="discord:jeff")
    ok, msg = await svc.request_stop(await reload(db, rec), actor="discord:other")
    assert not ok and "already running" in msg


@pytest.mark.asyncio
async def test_world_is_saved_before_every_stop(db):
    saved.clear()
    rec = await make(db)
    await svc.start(rec, actor=JEFF)
    await svc.stop(await reload(db, rec), actor=JEFF)
    assert saved == [rec["id"]]


@pytest.mark.asyncio
async def test_auto_stop_also_saves_the_world(db):
    """The 12h reaper must not be the one path that loses progress."""
    saved.clear()
    rec = await make(db)
    await svc.start(rec)
    await idle_for(db, rec, hours=12, minutes=1)
    await svc.reap()
    assert saved == [rec["id"]]


# ------------------------------------------ ownership of a running server --
@pytest.mark.asyncio
async def test_starter_can_stop_their_own_empty_server(db):
    rec = await make(db)
    await svc.start(rec, actor=JEFF)
    assert (await reload(db, rec))["started_by"] == JEFF
    ok, _msg = await svc.stop(await reload(db, rec), actor=JEFF)
    assert ok


@pytest.mark.asyncio
async def test_bystander_cannot_stop_someone_elses_empty_server(db):
    rec = await make(db)
    await svc.start(rec, actor=JEFF)
    ok, msg = await svc.stop(await reload(db, rec), actor="discord:Dave")
    assert not ok and "started by Jeff" in msg
    assert (await reload(db, rec))["status"] == "running"


@pytest.mark.asyncio
async def test_starter_cannot_stop_their_server_while_others_play(db):
    """Owning the server does not mean owning other people's sessions."""
    rec = await make(db)
    await svc.start(rec, actor=JEFF)
    await occupy(db, rec, players=2)
    ok, msg = await svc.stop(await reload(db, rec), actor=JEFF)
    assert not ok and "Only an admin" in msg


@pytest.mark.asyncio
async def test_admin_still_needs_force_to_end_live_sessions(db):
    """Being admin shouldn't let you kill a session by accident."""
    rec = await make(db)
    await svc.start(rec, actor=JEFF)
    await occupy(db, rec, players=2)
    ok, msg = await svc.stop(await reload(db, rec), actor=ADMIN, is_admin=True)
    assert not ok and "force:True" in msg
    ok, _ = await svc.stop(await reload(db, rec), actor=ADMIN, is_admin=True, force=True)
    assert ok


@pytest.mark.asyncio
async def test_stop_refreshes_the_player_count_before_deciding(db, monkeypatch):
    """An hour-stale count must not be what a stop decision rests on.

    The stored row says empty; a live query says two people just joined.
    The stop has to see the live answer.
    """
    rec = await make(db)
    await svc.start(rec, actor=JEFF)

    async def someone_just_joined(r):
        patch = gs.occupancy_patch(r, 2)
        await db.gameservers.update_one({"id": r["id"]}, {"$set": patch})
        return {**r, **patch}

    monkeypatch.setattr(svc, "poll_occupancy", someone_just_joined)
    ok, msg = await svc.stop(await reload(db, rec), actor=JEFF)
    assert not ok and "2 people are playing" in msg


@pytest.mark.asyncio
async def test_automation_bypasses_ownership_entirely(db):
    rec = await make(db)
    await svc.start(rec, actor=JEFF)
    await idle_for(db, rec, hours=12, minutes=1)
    stopped = await svc.reap()
    assert len(stopped) == 1
