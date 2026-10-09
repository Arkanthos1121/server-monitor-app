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


# ---- launch shapes verified against real installs --------------------------
def test_wine_launch_passes_env_through_env_not_as_the_program():
    # spawn() prefixes `setsid nohup`, which would exec "WINEPREFIX=..." literally.
    cmd = gs.build_launch({"name": "vr", "server_appid": 1829350, "port": 9876})
    assert cmd.startswith("env WINEPREFIX=")
    assert "VRisingServer.exe" in cmd and "xvfb-run" in cmd


def test_proton_launch_passes_env_through_env():
    cmd = gs.build_launch({"name": "asa", "server_appid": 2430930, "port": 7777})
    assert cmd.startswith("env STEAM_COMPAT_DATA_PATH=")
    assert "ArkAscendedServer.exe" in cmd


async def test_spawn_enters_the_profile_working_dir(as_remote, captured, monkeypatch):
    calls, rc = captured
    rc["out"] = b"777\n"
    monkeypatch.setattr(gs, "alive", _always_alive)
    await gs.spawn({"name": "trucks", "server_appid": 1948160, "port": 27015})
    assert "/opt/gameservers/trucks-1948160/bin/linux_x64" in calls[0][-1]


async def test_login_game_refuses_without_a_cached_account(as_remote, captured, monkeypatch):
    calls, _rc = captured
    monkeypatch.setattr(gs, "STEAMCMD_LOGIN", "")
    ok, msg = await gs.steamcmd_install({"name": "a3", "server_appid": 233780})
    assert not ok and "STEAMCMD_LOGIN" in msg and calls == []


async def test_login_game_uses_the_cached_account(as_remote, captured, monkeypatch):
    calls, _rc = captured
    monkeypatch.setattr(gs, "STEAMCMD_LOGIN", "someuser")
    await gs.steamcmd_install({"name": "a3", "server_appid": 233780})
    assert "+login someuser" in calls[0][-1] and "anonymous" not in calls[0][-1]


async def test_l4d2_installs_windows_then_linux(as_remote, captured):
    calls, _rc = captured
    await gs.steamcmd_install({"name": "l4d2", "server_appid": 222860})
    cmd = calls[0][-1]
    assert cmd.index("PlatformType windows") < cmd.index("PlatformType linux")


def test_profile_env_is_applied_to_native_launch():
    cmd = gs.build_launch({"name": "ins", "server_appid": 237410, "port": 27015})
    assert cmd.startswith("env LD_LIBRARY_PATH=")
    assert "/opt/gameservers/ins-237410/bin" in cmd and cmd.split()[2].endswith("srcds_linux")


async def test_proton_stop_reaches_the_whole_prefix(as_remote, captured):
    # Proton detaches the game from spawn()'s process group; killing the group
    # alone left SCUM running. The prefix's wineserver must be told too.
    calls, rc = captured
    rc["out"] = b"CLEAN\n"
    assert await gs.stop_prefix({"name": "scum", "server_appid": 3792580}, 5) == "prefix stopped cleanly"
    cmd = calls[0][-1]
    assert "scum-3792580/compatdata/pfx" in cmd
    # Signal glued to the flag: `-k 15` would send the default signal and pass
    # 15 as a stray argument, so SIGTERM-then-SIGKILL never actually happens.
    assert cmd.index("-k15") < cmd.index("-w") < cmd.index("-k9")


async def test_native_stop_skips_the_prefix_step(as_remote, captured):
    calls, _rc = captured
    assert await gs.stop_prefix({"name": "v", "server_appid": 896660}, 5) is None
    assert calls == []


async def test_prefix_stop_reports_a_missing_wineserver(as_remote, captured):
    """A wrong WINESERVER_PATH must not read as a successful stop."""
    _calls, rc = captured
    rc["rc"], rc["out"] = 3, b"NOWINESERVER\n"
    out = await gs.stop_prefix({"name": "scum", "server_appid": 3792580}, 5)
    assert "wineserver not found" in out


async def test_prefix_stop_reports_an_uncertain_result(as_remote, captured):
    _calls, rc = captured
    rc["out"] = b""
    out = await gs.stop_prefix({"name": "scum", "server_appid": 3792580}, 5)
    assert "uncertain" in out
