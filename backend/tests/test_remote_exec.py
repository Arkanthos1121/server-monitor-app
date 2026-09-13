"""Tests for driving a separate gameserver box over SSH.

The backend may live on a Pi that cannot run SteamCMD at all, so these paths
have to build correct remote commands without a real host to talk to.
"""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gameservers as gs  # noqa: E402


class FakeProc:
    def __init__(self, rc=0, out=b""):
        self.returncode = rc
        self._out = out

    async def communicate(self):
        return self._out, b""


@pytest.fixture
def captured(monkeypatch):
    """Capture argv instead of executing anything."""
    calls = []

    def fake_exec(*argv, **kw):
        calls.append(list(argv))

        async def _mk():
            return FakeProc(rc=calls_rc["rc"], out=calls_rc["out"])
        return _mk()

    calls_rc = {"rc": 0, "out": b""}
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    return calls, calls_rc


@pytest.fixture
def as_remote(monkeypatch):
    monkeypatch.setattr(gs, "SSH_HOST", "gameserver.lan")
    monkeypatch.setattr(gs, "SSH_USER", "steam")
    monkeypatch.setattr(gs, "SSH_PORT", "22")
    monkeypatch.setattr(gs, "SSH_KEY", "/keys/id_ed25519")


def test_local_by_default(monkeypatch):
    monkeypatch.setattr(gs, "SSH_HOST", "")
    assert gs.remote() is False


def test_remote_when_host_configured(as_remote):
    assert gs.remote() is True


def test_ssh_argv_carries_key_port_and_target(as_remote):
    argv = gs._ssh_argv()
    assert argv[0] == "ssh"
    assert "steam@gameserver.lan" == argv[-1]
    assert "-i" in argv and "/keys/id_ed25519" in argv
    assert "-p" in argv and "22" in argv
    assert "BatchMode=yes" in argv  # never hang waiting for a password prompt


async def test_run_shell_local_uses_bash(monkeypatch, captured):
    monkeypatch.setattr(gs, "SSH_HOST", "")
    calls, _ = captured
    await gs.run_shell("echo hi")
    assert calls[0][:2] == ["bash", "-lc"]


async def test_run_shell_remote_goes_through_ssh(as_remote, captured):
    calls, _ = captured
    await gs.run_shell("echo hi")
    assert calls[0][0] == "ssh"
    assert calls[0][-1] == "echo hi"
    assert "steam@gameserver.lan" in calls[0]


async def test_alive_remote_uses_kill_zero(as_remote, captured):
    calls, rc = captured
    rc["rc"] = 0
    assert await gs.alive({"pid": 1234}) is True
    assert "kill -0 1234" in calls[0][-1]


async def test_alive_remote_false_on_nonzero_exit(as_remote, captured):
    calls, rc = captured
    rc["rc"] = 1
    assert await gs.alive({"pid": 1234}) is False


async def test_alive_without_pid_never_shells_out(as_remote, captured):
    calls, _ = captured
    assert await gs.alive({"pid": None}) is False
    assert calls == []


async def test_install_builds_steamcmd_command_remotely(as_remote, captured):
    calls, rc = captured
    rc["out"] = b"Success! App '896660' fully installed."
    ok, out = await gs.steamcmd_install({"name": "valheim-main", "server_appid": 896660})
    cmd = calls[0][-1]
    assert ok
    assert "+login anonymous" in cmd and "+app_update 896660" in cmd
    assert "mkdir -p" in cmd


async def test_install_reports_missing_steamcmd_on_the_right_host(as_remote, captured):
    _calls, rc = captured
    rc["rc"] = 127
    ok, msg = await gs.steamcmd_install({"name": "v", "server_appid": 896660})
    assert not ok and "steam@gameserver.lan" in msg


async def test_spawn_detaches_and_returns_pid(as_remote, captured, monkeypatch):
    calls, rc = captured
    rc["out"] = b"40321\n"
    monkeypatch.setattr(gs, "alive", _always_alive)
    rec = {"name": "valheim-main", "server_appid": 896660, "port": 2456,
           "server_password": "secret", "max_players": 10}
    pid, ticks, msg = await gs.spawn(rec)
    cmd = calls[0][-1]
    assert pid == 40321 and ticks is None
    assert "setsid" in cmd and "nohup" in cmd     # survives the SSH session
    assert cmd.rstrip().endswith("echo $!")       # so we learn the PID


async def test_spawn_reports_missing_install(as_remote, captured):
    _calls, rc = captured
    rc["rc"] = 66
    pid, _t, msg = await gs.spawn({"name": "v", "server_appid": 896660, "port": 1})
    assert pid is None and "install it first" in msg


async def test_remote_terminate_escalates_to_kill(as_remote, captured):
    calls, rc = captured
    rc["out"] = b"KILLED\n"
    assert await gs.terminate(555, grace=2) == "force-killed after grace period"
    assert "kill -TERM -555" in calls[1][-1]
    assert "kill -KILL -555" in calls[1][-1]


async def test_remote_terminate_clean_stop(as_remote, captured):
    _calls, rc = captured
    rc["out"] = b"CLEAN\n"
    assert await gs.terminate(555, grace=2) == "stopped cleanly"


async def test_remote_terminate_noop_when_already_dead(as_remote, captured):
    calls, rc = captured
    rc["rc"] = 1
    assert await gs.terminate(555) == "already stopped"
    assert len(calls) == 1     # checked, then gave up - no signals sent


async def _always_alive(rec):
    return True
