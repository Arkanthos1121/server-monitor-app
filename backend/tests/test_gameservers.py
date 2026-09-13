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


# ----------------------------------------------------------- the 12h rule --
def test_initial_deadline_is_twelve_hours_out():
    assert gs.initial_deadline(NOW) == NOW + timedelta(hours=gs.AUTO_STOP_HOURS)
    assert gs.AUTO_STOP_HOURS == 12


def test_not_due_before_twelve_hours():
    rec = running()
    assert not gs.is_due(rec, NOW + timedelta(hours=11, minutes=59))


def test_due_at_twelve_hours():
    rec = running()
    assert gs.is_due(rec, NOW + timedelta(hours=12))
    assert gs.is_due(rec, NOW + timedelta(hours=12, seconds=1))


def test_keepalive_exempts_from_auto_stop():
    rec = running(keepalive=True)
    assert not gs.is_due(rec, NOW + timedelta(days=7))
    assert gs.remaining_seconds(rec, NOW) is None


def test_stopped_server_is_never_due():
    rec = running(status="stopped")
    assert not gs.is_due(rec, NOW + timedelta(days=1))


# -------------------------------------------------------------- extending --
def test_extend_is_relative_to_now_not_to_old_deadline():
    """/extend 2 means two hours from now, even with 11h already on the clock."""
    later = NOW + timedelta(hours=1)
    assert gs.extended_deadline(2, later) == later + timedelta(hours=2)


def test_extend_is_clamped_to_max():
    got = gs.extended_deadline(9999, NOW)
    assert got == NOW + timedelta(hours=gs.MAX_EXTEND_HOURS)


def test_extend_rejects_nonsense_small_values():
    assert gs.extended_deadline(0, NOW) == NOW + timedelta(hours=0.25)
    assert gs.extended_deadline(-5, NOW) == NOW + timedelta(hours=0.25)


def test_extend_clears_a_due_server():
    rec = running()
    late = NOW + timedelta(hours=13)
    assert gs.is_due(rec, late)
    rec["auto_stop_at"] = gs.extended_deadline(3, late)
    assert not gs.is_due(rec, late)


def test_deadline_accepts_isoformat_from_mongo():
    rec = running(auto_stop_at=gs.initial_deadline(NOW).isoformat())
    assert gs.is_due(rec, NOW + timedelta(hours=12, minutes=1))
    assert not gs.is_due(rec, NOW + timedelta(hours=1))


def test_naive_datetime_is_treated_as_utc():
    rec = running(auto_stop_at=(NOW + timedelta(hours=12)).replace(tzinfo=None))
    assert gs.is_due(rec, NOW + timedelta(hours=12, minutes=1))


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
