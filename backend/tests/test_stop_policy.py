"""Tests for who may stop a server.

These encode the anti-griefing rules, so they are deliberately exhaustive about
the awkward combinations - the starter trying to end someone else's session, a
bystander closing a server that isn't theirs, automation always winning.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stop_policy as sp  # noqa: E402

JEFF = "discord:Jeff"
DAVE = "discord:Dave"


def server(players=0, starter=JEFF, name="ark-main"):
    return {"name": name, "players_online": players, "started_by": starter}


# ------------------------------------------------- occupied servers --------
def test_bystander_cannot_stop_an_occupied_server():
    d = sp.may_stop(server(players=2), DAVE, is_admin=False)
    assert not d.allowed
    assert "2 people are playing" in d.reason
    assert "requeststop" in d.reason


def test_the_starter_cannot_stop_an_occupied_server_either():
    """The key rule: starting a server does not grant power over other people's sessions."""
    d = sp.may_stop(server(players=3, starter=JEFF), JEFF, is_admin=False)
    assert not d.allowed
    assert "Only an admin" in d.reason


def test_admin_can_stop_an_occupied_server():
    d = sp.may_stop(server(players=3), DAVE, is_admin=True)
    assert d.allowed and d.needs_force


def test_singular_wording_for_a_single_player():
    d = sp.may_stop(server(players=1), DAVE)
    assert "1 person is playing" in d.reason


# ---------------------------------------------------- empty servers --------
def test_starter_can_stop_their_own_empty_server():
    assert sp.may_stop(server(players=0, starter=JEFF), JEFF).allowed


def test_bystander_cannot_stop_someone_elses_empty_server():
    d = sp.may_stop(server(players=0, starter=JEFF), DAVE)
    assert not d.allowed
    assert "started by Jeff" in d.reason


def test_admin_can_stop_any_empty_server():
    assert sp.may_stop(server(players=0, starter=JEFF), DAVE, is_admin=True).allowed


def test_open_policy_lets_anyone_stop_an_empty_server():
    d = sp.may_stop(server(players=0, starter=JEFF), DAVE, policy="anyone")
    assert d.allowed


def test_open_policy_still_protects_an_occupied_server():
    """Relaxing the empty-server rule must not weaken the griefing guard."""
    d = sp.may_stop(server(players=2, starter=JEFF), DAVE, policy="anyone")
    assert not d.allowed


def test_server_with_no_recorded_owner_can_be_stopped():
    """Servers started before this rule existed shouldn't become unstoppable."""
    assert sp.may_stop(server(players=0, starter=None), DAVE).allowed


# ------------------------------------------------------- automation --------
@pytest.mark.parametrize("actor", ["auto-stop", "stop-request", "reaper"])
def test_automation_always_wins(actor):
    assert sp.may_stop(server(players=5), actor).allowed
    assert sp.may_stop(server(players=0, starter=JEFF), actor).allowed


def test_a_user_cannot_impersonate_automation_by_name():
    """'discord:auto-stop' is a person, not the reaper."""
    assert not sp.is_automation("discord:auto-stop")


# ------------------------------------------------------- comparisons -------
def test_actor_match_is_case_insensitive():
    assert sp.same_person("discord:Jeff", "discord:jeff")
    assert not sp.same_person("discord:Jeff", "discord:Jeffrey")


def test_missing_actors_never_match():
    assert not sp.same_person("", "")
    assert not sp.same_person(None, "discord:Jeff")


def test_decision_unpacks_like_a_tuple():
    ok, why = sp.may_stop(server(players=0), JEFF)
    assert ok is True and isinstance(why, str)
