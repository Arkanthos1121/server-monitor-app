"""Who is allowed to stop a game server.

The rule set, in plain terms:

  - Automation (the idle reaper, an un-vetoed stop request) may always stop.
  - While people are playing, ONLY an admin may stop the server. Not even the
    person who started it - "I started it so I can end your session" is exactly
    the griefing this is meant to prevent.
  - While the server is empty, the person who started it may stop it, and so
    may an admin. Everyone else is refused, so a server someone spun up for
    their evening isn't casually closed by a bystander.

`EMPTY_STOP_POLICY=anyone` relaxes the last rule for groups that would rather
let anybody free up RAM on an idle server.
"""
from __future__ import annotations

import os

# Actors that are the system acting on its own behalf, not a person.
AUTOMATION_ACTORS = {"auto-stop", "stop-request", "reaper", "shutdown"}

EMPTY_STOP_POLICY = os.environ.get("GAMESERVER_EMPTY_STOP_POLICY", "starter").lower()


class Decision:
    """Whether a stop may proceed, and what to tell the person if not."""

    def __init__(self, allowed: bool, reason: str = "", needs_force: bool = False):
        self.allowed = allowed
        self.reason = reason
        self.needs_force = needs_force

    def __iter__(self):            # so callers can do `ok, why = decision`
        return iter((self.allowed, self.reason))

    def __repr__(self):
        return f"Decision(allowed={self.allowed!r}, reason={self.reason!r})"


def is_automation(actor: str) -> bool:
    return (actor or "").split(":", 1)[0] in AUTOMATION_ACTORS


def same_person(a: str, b: str) -> bool:
    """Compare Discord actor strings ('discord:Name#1234') case-insensitively."""
    if not a or not b:
        return False
    return a.strip().lower() == b.strip().lower()


def may_stop(rec: dict, actor: str, is_admin: bool = False,
             policy: str = None) -> Decision:
    """Decide whether `actor` may stop this server right now."""
    policy = (policy or EMPTY_STOP_POLICY).lower()
    name = rec.get("name", "this server")

    if is_automation(actor):
        return Decision(True, "automation")

    players = rec.get("players_online") or 0
    starter = rec.get("started_by")

    if players > 0:
        if is_admin:
            return Decision(True, f"admin override with {players} online",
                            needs_force=True)
        who = "1 person is" if players == 1 else f"{players} people are"
        return Decision(False,
                        f"{who} playing on **{name}** right now. Only an admin can "
                        f"stop an occupied server.\n"
                        f"Use `/requeststop {name}` to ask them to wrap up — "
                        f"they get a few minutes' notice and can decline.")

    # Server is empty from here on.
    if is_admin:
        return Decision(True, "admin")
    if policy == "anyone":
        return Decision(True, "empty server, open policy")
    if starter and same_person(actor, starter):
        return Decision(True, "started by this person")
    if not starter:
        # Nobody recorded as owner (started before this rule, or via the app).
        return Decision(True, "no recorded owner")
    return Decision(False,
                    f"**{name}** was started by {_display(starter)}. "
                    f"They or an admin can stop it.")


def _display(actor: str) -> str:
    """Strip the 'discord:' prefix for messages shown to people."""
    return actor.split(":", 1)[1] if ":" in actor else actor
