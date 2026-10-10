"""The channel-permission section of the Discord diagnosis.

Commands registered to a guild still will not appear in a channel the bot
cannot see. The diagnosis checked guild-level registration only, so a channel
the bot had no access to looked identical to everything being fine.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("dd", BACKEND / "diagnose_discord.py")
dd = importlib.util.module_from_spec(_spec)
sys.modules["dd"] = dd
_spec.loader.exec_module(dd)


def chan(name, cid=1, view=True, send=True, use_cmds=True, guild="G"):
    return {"guild": guild, "id": cid, "name": name,
            "view": view, "send": send, "use_cmds": use_cmds}


def run(chans, channel_id=""):
    problems: list[str] = []
    dd.report_channels(chans, channel_id, problems)
    return problems


def test_all_good_channels_raise_no_problem():
    assert run([chan("general", 1), chan("server-launcher", 2)]) == []


def test_a_bot_with_no_usable_channel_is_a_problem():
    problems = run([chan("general", 1, view=False),
                    chan("secret", 2, use_cmds=False)])
    assert len(problems) == 1
    assert "no channel it can be used in" in problems[0]


def test_an_invisible_channel_does_not_hide_the_usable_ones(capsys):
    run([chan("general", 1), chan("staff", 2, view=False)])
    out = capsys.readouterr().out
    assert "#general" in out
    assert "not usable: #staff" in out


def test_configured_channel_the_bot_cannot_see_is_flagged():
    problems = run([chan("general", 1)], channel_id="999")
    assert len(problems) == 1
    assert "999" in problems[0] and "not visible" in problems[0]


def test_configured_channel_without_command_permission_is_flagged():
    problems = run([chan("server-launcher", 42, use_cmds=False)], channel_id="42")
    assert any("server-launcher" in p for p in problems)
    assert any("Use Application Commands" in p for p in problems)


def test_configured_channel_that_is_fine_raises_nothing(capsys):
    assert run([chan("server-launcher", 42)], channel_id="42") == []
    assert "#server-launcher" in capsys.readouterr().out


def test_no_channel_data_is_a_warning_not_a_crash(capsys):
    assert run([]) == []
    assert "Could not read channel permissions" in capsys.readouterr().out


def test_channel_id_is_compared_as_a_string_not_an_int():
    """Ids come from the environment as strings and from Discord as ints."""
    assert run([chan("ok", 1553522833785622669)],
               channel_id="1553522833785622669") == []
