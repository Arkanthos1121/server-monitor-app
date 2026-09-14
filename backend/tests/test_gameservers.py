"""Tests for the 12-hour auto-stop rule and process-liveness handling."""
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gameservers as gs  # noqa: E402

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)


def running(**kw):
    rec = {"status": "running", "auto_stop_at": gs.initial_deadline(NOW), "keepalive": False}
    rec.update(kw)
    return rec


# --------------------------------------------------- the 12h IDLE rule -----
def empty_for(hours, **kw):
    """A running server that has had nobody on it for `hours`."""
    rec = {"status": "running", "players_online": 0, "players_known": True,
           "empty_since": (NOW - timedelta(hours=hours)).isoformat(),
           "keepalive": False}
    rec.update(kw)
    return rec


def occupied(players=3, **kw):
    rec = {"status": "running", "players_online": players, "players_known": True,
           "empty_since": None, "keepalive": False}
    rec.update(kw)
    return rec


def test_idle_window_is_twelve_hours():
    assert gs.AUTO_STOP_HOURS == 12


def test_not_due_before_twelve_idle_hours():
    assert not gs.is_due(empty_for(11.9), NOW)


def test_due_after_twelve_idle_hours():
    assert gs.is_due(empty_for(12), NOW)
    assert gs.is_due(empty_for(30), NOW)


def test_occupied_server_is_never_due_however_long_it_has_run():
    """The whole point of the change: people playing keeps it alive."""
    rec = occupied(players=1, started_at=(NOW - timedelta(days=5)).isoformat())
    assert not gs.is_due(rec, NOW)
    assert gs.remaining_seconds(rec, NOW) is None


def test_idle_clock_resets_when_someone_joins():
    rec = empty_for(11)
    assert gs.idle_seconds(rec, NOW) == pytest.approx(11 * 3600, abs=2)
    rec.update(gs.occupancy_patch(rec, 2, NOW))      # someone joins
    assert rec["empty_since"] is None
    assert gs.idle_seconds(rec, NOW) is None
    assert not gs.is_due(rec, NOW)


def test_idle_clock_starts_when_the_last_player_leaves():
    rec = occupied(players=1)
    rec.update(gs.occupancy_patch(rec, 0, NOW))      # they log off
    assert rec["players_online"] == 0
    assert gs.idle_seconds(rec, NOW) == pytest.approx(0, abs=2)
    assert not gs.is_due(rec, NOW)
    assert gs.is_due(rec, NOW + timedelta(hours=12, minutes=1))


def test_idle_clock_is_not_restarted_by_repeated_empty_polls():
    """Polling every minute must not keep pushing the deadline away."""
    rec = empty_for(11)
    first = rec["empty_since"]
    for _ in range(5):
        rec.update(gs.occupancy_patch(rec, 0, NOW))
    assert rec["empty_since"] == first


def test_unqueryable_server_falls_back_to_uptime():
    """If we can't ask, the server still has to shut down eventually."""
    rec = {"status": "running", "keepalive": False, "empty_since": None,
           "started_at": (NOW - timedelta(hours=13)).isoformat()}
    rec.update(gs.occupancy_patch(rec, None, NOW))
    assert rec["players_known"] is False
    assert gs.is_due(rec, NOW)


def test_unknown_count_does_not_wipe_a_known_occupancy():
    rec = occupied(players=4)
    rec.update(gs.occupancy_patch(rec, None, NOW))
    assert rec["players_online"] == 4        # a failed poll is not "empty"
    assert not gs.is_due(rec, NOW)


def test_keepalive_exempts_from_idle_stop():
    assert not gs.is_due(empty_for(48, keepalive=True), NOW)
    assert gs.remaining_seconds(empty_for(48, keepalive=True), NOW) is None


def test_stopped_server_is_never_due():
    assert not gs.is_due(empty_for(48, status="stopped"), NOW)


# -------------------------------------------------------------- extending --
def test_extend_is_relative_to_now():
    later = NOW + timedelta(hours=1)
    assert gs.extended_deadline(2, later) == later + timedelta(hours=2)


def test_extend_is_clamped_to_max():
    assert gs.extended_deadline(9999, NOW) == NOW + timedelta(hours=gs.MAX_EXTEND_HOURS)


def test_extend_rejects_nonsense_small_values():
    assert gs.extended_deadline(0, NOW) == NOW + timedelta(hours=0.25)
    assert gs.extended_deadline(-5, NOW) == NOW + timedelta(hours=0.25)


def test_grace_keeps_an_idle_server_alive():
    rec = empty_for(20, idle_grace_until=(NOW + timedelta(hours=2)).isoformat())
    assert not gs.is_due(rec, NOW)
    assert gs.remaining_seconds(rec, NOW) == pytest.approx(2 * 3600, abs=2)


def test_server_dies_once_the_grace_expires():
    rec = empty_for(20, idle_grace_until=(NOW - timedelta(minutes=1)).isoformat())
    assert gs.is_due(rec, NOW)


# --------------------------------------------------------------- humanize --
@pytest.mark.parametrize("secs,want", [
    (None, "no auto-stop"), (0, "stopping now"), (-10, "stopping now"),
    (90 * 60, "1h 30m"), (45 * 60, "45m"), (12 * 3600, "12h 0m"),
])
def test_fmt_remaining(secs, want):
    assert gs.fmt_remaining(secs) == want


# --------------------------------------------------------------- liveness --
def test_is_alive_for_current_process():
    assert gs.is_alive(os.getpid())


def test_is_alive_false_for_none_and_bogus_pid():
    assert not gs.is_alive(None)
    assert not gs.is_alive(0)
    assert not gs.is_alive(4194303)


def test_pid_reuse_is_detected_via_start_ticks():
    """A recycled PID must not be mistaken for our still-running server."""
    pid = os.getpid()
    real = gs._proc_start_ticks(pid)
    if real is None:
        pytest.skip("/proc not available")
    assert gs.is_alive(pid, real)
    assert not gs.is_alive(pid, real + 5000)
