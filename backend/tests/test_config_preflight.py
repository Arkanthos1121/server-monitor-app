"""The boot-time config check, and the example file it is usually fed from.

A whole class of "the app is mysteriously down" came from .env.example: it
carried its instructions as inline comments on the value lines, so
`cp .env.example .env` produced an empty SERVER_ENC_KEY, Fernet raised during
module import, and uvicorn restart-looped with a traceback that named neither
the variable nor the fix. These pin both halves of that.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
EXAMPLE = BACKEND.parent / "selfhost" / ".env.example"


def env_lines():
    return [ln.rstrip("\n") for ln in EXAMPLE.read_text().splitlines()]


def assignments():
    """(key, raw_value) for every assignment line in .env.example."""
    out = []
    for ln in env_lines():
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", ln)
        if m:
            out.append((m.group(1), m.group(2)))
    return out


# ------------------------------------------------------- the example file ---
def test_example_file_exists():
    assert EXAMPLE.is_file(), f"{EXAMPLE} is missing"


def test_no_inline_comments_on_value_lines():
    """`KEY=value  # note` parses differently across Compose versions.

    When it is stripped, a required key silently becomes empty and the backend
    cannot boot. Comments belong on their own line.
    """
    bad = [ln for ln in env_lines()
           if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=.*#", ln)]
    assert bad == [], f"move these comments onto their own line: {bad}"


def test_no_value_has_trailing_whitespace():
    """Trailing spaces survive parsing and corrupt a key or an int."""
    bad = [k for k, v in assignments() if v != v.rstrip()]
    assert bad == [], f"trailing whitespace after: {bad}"


def test_every_numeric_default_actually_parses_as_an_int():
    numeric = [k for k, _ in assignments()
               if k.endswith(("_SECONDS", "_HOURS", "_MIN", "_GRACE", "_PORT"))]
    assert numeric, "expected some numeric settings"
    for k, v in assignments():
        if k in numeric and v:
            int(v)          # raises if a comment or unit crept in


def test_required_keys_are_present_and_blank():
    """The two secrets must ship empty: a shared default key is worse than none."""
    vals = dict(assignments())
    for k in ("MONGO_URL", "DB_NAME", "JWT_SECRET", "SERVER_ENC_KEY"):
        assert k in vals, f"{k} missing from .env.example"
    assert vals["JWT_SECRET"] == ""
    assert vals["SERVER_ENC_KEY"] == ""


# --------------------------------------------------------- the preflight ----
def boot(**env):
    """Import server.py with a given environment; return (rc, output)."""
    base = {"PATH": os.environ["PATH"], "PYTHONPATH": str(BACKEND)}
    p = subprocess.run([sys.executable, "-c", "import server"],
                       cwd=BACKEND, env={**base, **env},
                       capture_output=True, text=True, timeout=120)
    return p.returncode, p.stdout + p.stderr


def fernet_key() -> str:
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode()


GOOD = {"MONGO_URL": "mongodb://localhost:27017", "DB_NAME": "webminpulse",
        "JWT_SECRET": "s"}


def test_empty_enc_key_is_reported_not_raised():
    rc, out = boot(**GOOD, SERVER_ENC_KEY="")
    assert rc == 1
    assert "SERVER_ENC_KEY is empty" in out
    assert "Traceback" not in out, "a traceback tells the user nothing"


def test_malformed_enc_key_names_the_problem_and_its_length():
    rc, out = boot(**GOOD, SERVER_ENC_KEY="not-a-real-key")
    assert rc == 1
    assert "not a valid Fernet key" in out and "yours is 14" in out
    assert "Fernet.generate_key" in out, "must print the generating command"


def test_every_missing_core_var_is_listed_in_one_go():
    """Reporting one at a time means one restart cycle per variable."""
    rc, out = boot(MONGO_URL="", DB_NAME="", JWT_SECRET="", SERVER_ENC_KEY="")
    assert rc == 1
    for var in ("MONGO_URL", "DB_NAME", "JWT_SECRET", "SERVER_ENC_KEY"):
        assert var in out


def test_the_message_points_at_recovering_the_old_key():
    """A new key cannot decrypt what the old one wrote - say so before they act."""
    rc, out = boot(**GOOD, SERVER_ENC_KEY="")
    assert "docker inspect" in out and "re-enter" in out


def test_a_valid_config_imports_cleanly():
    rc, out = boot(**GOOD, SERVER_ENC_KEY=fernet_key())
    assert rc == 0, out
    assert "cannot start" not in out
