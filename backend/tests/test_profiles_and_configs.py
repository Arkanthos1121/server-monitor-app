"""Tests for launch profiles, starter configs, and the profile verifier.

Many profile paths were written from each game's documentation rather than a
verified install, so these tests pin the things that CAN be checked offline:
internal consistency, that every declared config ships a template, and that
rendering never mangles config syntax or clobbers someone's edits.
"""
import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import gameservers as gs  # noqa: E402
from steam import profiles, verify_profiles  # noqa: E402


# -------------------------------------------------------- profile shape ----
@pytest.mark.parametrize("appid", sorted(profiles.PROFILES))
def test_profile_has_the_required_fields(appid):
    p = profiles.PROFILES[appid]
    for key in ("game", "port", "players", "args"):
        assert key in p, f"{appid} missing {key}"
    assert isinstance(p["port"], int) and 0 < p["port"] < 65536
    assert isinstance(p["players"], int) and p["players"] > 0
    assert "linux" in p or "windows" in p


@pytest.mark.parametrize("appid", sorted(profiles.PROFILES))
def test_every_profile_can_run_somewhere(appid):
    """A profile with no usable binary for its runner can never start."""
    p = profiles.PROFILES[appid]
    run_with = p.get("runner", "native")
    binary = p["windows"] if run_with in ("proton", "wine") else p.get("linux")
    assert binary, f"{p['game']} has runner={run_with} but no binary for it"


@pytest.mark.parametrize("appid", sorted(profiles.PROFILES))
def test_args_only_use_known_placeholders(appid):
    """A typo'd placeholder would blow up at launch, not here."""
    import string
    known = {"dir", "name", "port", "password", "players"}
    for _lit, field, _spec, _conv in string.Formatter().parse(profiles.PROFILES[appid]["args"]):
        if field:
            assert field in known, f"{appid} uses unknown placeholder {{{field}}}"


def test_wine_and_proton_profiles_declare_a_windows_binary():
    for appid, p in profiles.PROFILES.items():
        if p.get("runner") in ("wine", "proton"):
            assert p.get("windows"), f"{p['game']} runs under {p['runner']} with no .exe"


def test_games_needing_a_steam_login_are_flagged():
    """Arma 3 and DayZ reject anonymous SteamCMD; that has to be discoverable."""
    flagged = {p["game"] for p in profiles.PROFILES.values() if p.get("needs_steam_login")}
    assert "Arma 3" in flagged and "DayZ" in flagged
    assert profiles.needs_steam_login({"server_appid": 233780})
    assert not profiles.needs_steam_login({"server_appid": 896660})


# ------------------------------------------------------- config coverage ---
def test_every_declared_config_ships_a_template():
    """A profile promising a config with no template fails silently at install."""
    missing = []
    for appid, p in profiles.PROFILES.items():
        for rel in p.get("configs") or []:
            if not (BACKEND / "gameconfigs" / str(appid) / rel).is_file():
                missing.append(f"{p['game']}: {rel}")
    assert missing == [], f"declared but not shipped: {missing}"


def test_no_orphan_templates():
    """A template no profile references would never be written."""
    root = BACKEND / "gameconfigs"
    declared = {
        str(root / str(appid) / rel)
        for appid, p in profiles.PROFILES.items()
        for rel in (p.get("configs") or [])
    }
    on_disk = {str(Path(dp) / fn) for dp, _dn, fns in os.walk(root) for fn in fns}
    assert on_disk - declared == set()


def test_config_files_accessor():
    assert profiles.config_files({"server_appid": 233780}) == ["server.cfg"]
    assert profiles.config_files({"server_appid": 896660}) == []
    assert profiles.config_files({}) == []


# ---------------------------------------------------------- rendering -----
def rec(**kw):
    base = {"name": "arma-main", "server_appid": 233780, "port": 2302,
            "max_players": 32, "server_password": "joinpw", "rcon_password": "adminpw"}
    base.update(kw)
    return base


def test_renders_values_into_the_template():
    out = gs.render_config(233780, "server.cfg", rec())
    assert 'hostname        = "arma-main";' in out
    assert 'passwordAdmin   = "adminpw";' in out
    assert "maxPlayers      = 32;" in out


def test_rendering_preserves_literal_braces():
    """Arma, DayZ and SII configs are full of braces; $-placeholders protect them."""
    out = gs.render_config(233780, "server.cfg", rec())
    assert 'motd[]          = {"arma-main"};' in out
    assert "class Missions {};" in out


def test_dayz_class_block_survives_rendering():
    out = gs.render_config(223350, "serverDZ.cfg", rec(server_appid=223350))
    assert "class Missions" in out and "template = \"dayzOffline.chernarusplus\";" in out


def test_sii_braces_survive_rendering():
    out = gs.render_config(1948160, "server_config.sii", rec(server_appid=1948160))
    assert out.startswith("SiiNunit")
    assert "server_config : _nameless.1 {" in out


def test_admin_password_falls_back_to_server_password():
    out = gs.render_config(233780, "server.cfg", rec(rcon_password=None))
    assert 'passwordAdmin   = "joinpw";' in out


def test_missing_template_returns_none_rather_than_raising():
    assert gs.render_config(233780, "nope.cfg", rec()) is None
    assert gs.render_config(999999, "server.cfg", rec()) is None


def test_unset_placeholder_is_left_alone_not_crashed_on():
    """safe_substitute: an unknown $token survives instead of raising."""
    out = gs.render_config(403240, "SquadGame/ServerConfig/Admins.cfg",
                           rec(server_appid=403240))
    assert "Group=Admin" in out


# ------------------------------------------------------- write_configs ----
@pytest.mark.asyncio
async def test_writes_configs_and_skips_existing(tmp_path, monkeypatch):
    """An existing config is someone's tuning - a reinstall must not clobber it."""
    monkeypatch.setattr(gs, "BASE_DIR", tmp_path)
    monkeypatch.setattr(gs, "SSH_HOST", "")
    r = rec()
    target = gs.install_dir(r) / "server.cfg"

    assert await gs.write_configs(r) == ["server.cfg"]
    assert target.is_file() and "arma-main" in target.read_text()

    target.write_text("# hand-tuned by Jeff\n")
    assert await gs.write_configs(r) == []            # reported as not written
    assert target.read_text() == "# hand-tuned by Jeff\n"


@pytest.mark.asyncio
async def test_writes_nested_config_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(gs, "BASE_DIR", tmp_path)
    monkeypatch.setattr(gs, "SSH_HOST", "")
    r = rec(name="dst-main", server_appid=343050, port=10999)
    written = await gs.write_configs(r)
    assert sorted(written) == ["cluster/Master/server.ini", "cluster/cluster.ini"]
    assert (gs.install_dir(r) / "cluster" / "Master" / "server.ini").is_file()


@pytest.mark.asyncio
async def test_game_with_no_configs_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(gs, "BASE_DIR", tmp_path)
    monkeypatch.setattr(gs, "SSH_HOST", "")
    assert await gs.write_configs(rec(server_appid=896660)) == []


# --------------------------------------------------------- the verifier ---
def test_verifier_accepts_a_correct_path(tmp_path):
    (tmp_path / "896660").mkdir()
    (tmp_path / "896660" / "valheim_server.x86_64").touch()
    assert verify_profiles.check(896660, profiles.PROFILES[896660], tmp_path)["state"] == "ok"


def test_verifier_flags_a_wrong_path_and_suggests_the_real_one(tmp_path):
    root = tmp_path / "233780"
    (root / "linux64").mkdir(parents=True)
    real = root / "linux64" / "arma3server_x64"
    real.touch(); real.chmod(0o755)
    row = verify_profiles.check(233780, profiles.PROFILES[233780], tmp_path)
    assert row["state"] == "MISSING"
    assert "linux64/arma3server_x64" in row["candidates"]


def test_verifier_ignores_steam_redistributables(tmp_path):
    root = tmp_path / "233780"
    root.mkdir()
    for noise in ("steamclient.so", "steamerrorreporter", "libsteam_api.so"):
        (root / noise).touch()
    row = verify_profiles.check(233780, profiles.PROFILES[233780], tmp_path)
    assert row["candidates"] == []


def test_verifier_reports_uninstalled_rather_than_failing(tmp_path):
    assert verify_profiles.check(896660, profiles.PROFILES[896660],
                                 tmp_path)["state"] == "not installed"


def test_verifier_checks_the_windows_binary_for_wine_profiles(tmp_path):
    root = tmp_path / "3792580"
    root.mkdir()
    row = verify_profiles.check(3792580, profiles.PROFILES[3792580], tmp_path)
    assert row["runner"] == "wine"
    assert row["declared"].endswith(".exe")


def test_verifier_finds_slug_suffixed_install_dirs(tmp_path):
    """install_dir() names dirs <slug>-<appid>; the verifier must find those too."""
    d = tmp_path / "valheim-main-896660"
    d.mkdir()
    (d / "valheim_server.x86_64").touch()
    assert verify_profiles.check(896660, profiles.PROFILES[896660], tmp_path)["state"] == "ok"
