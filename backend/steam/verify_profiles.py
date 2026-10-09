"""Check launch profiles against what SteamCMD actually installed.

Many profile binary paths come from each game's server documentation rather
than from a verified install. Documentation drifts and vendors move binaries,
so run this after installing and fix anything it flags — a wrong path means
`/start` fails with "Server binary missing" and nothing more useful.

    python3 -m steam.verify_profiles                 # check every install
    python3 -m steam.verify_profiles --dir /srv/gs   # non-default base dir
    python3 -m steam.verify_profiles 896660 233780   # just these appids
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    from steam import profiles
except ImportError:                                  # run directly, not as -m
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from steam import profiles

DEFAULT_BASE = Path(os.environ.get("GAMESERVER_BASE_DIR", "/opt/gameservers"))

# Things that look like a server executable but are not the one we want.
NOISE = ("steamclient", "crashhandler", "steamerrorreporter", "unitycrash",
         "libsteam", "steamcmd")


def install_dirs(base: Path, appid: int) -> list[Path]:
    """Every directory under base that belongs to this app id."""
    if not base.is_dir():
        return []
    exact = base / str(appid)
    hits = [exact] if exact.is_dir() else []
    hits += [d for d in base.iterdir()
             if d.is_dir() and d != exact and d.name.endswith(f"-{appid}")]
    return hits


def candidates(root: Path, limit: int = 12) -> list[str]:
    """Plausible server executables inside an install, for when a path is wrong."""
    out = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            low = fn.lower()
            if any(n in low for n in NOISE):
                continue
            looks_exe = (low.endswith((".sh", ".exe", ".bat"))
                         or "server" in low
                         or low.endswith(("-bin", "_x64", ".x86_64")))
            if not looks_exe:
                continue
            p = Path(dirpath) / fn
            if low.endswith((".sh", ".exe", ".bat")) or os.access(p, os.X_OK):
                out.append(str(p.relative_to(root)))
        if len(out) > limit * 4:
            break
    out.sort(key=len)
    return out[:limit]


def check(appid: int, prof: dict, base: Path) -> dict:
    roots = install_dirs(base, appid)
    run_with = prof.get("runner", "native")
    declared = prof["windows"] if run_with in ("proton", "wine") else prof.get("linux")

    row = {"appid": appid, "game": prof["game"], "runner": run_with,
           "declared": declared, "state": "", "detail": ""}

    if not roots:
        row["state"] = "not installed"
        return row
    root = roots[0]
    row["detail"] = str(root)

    if not declared:
        row["state"] = "no binary for this platform"
        return row
    if (root / declared).exists():
        row["state"] = "ok"
        return row

    row["state"] = "MISSING"
    row["candidates"] = candidates(root)
    return row


def check_configs(appid: int, prof: dict, base: Path) -> list[str]:
    """Declared config files that have no template shipped in the repo."""
    tpl_root = Path(__file__).resolve().parents[1] / "gameconfigs" / str(appid)
    return [rel for rel in (prof.get("configs") or [])
            if not (tpl_root / rel).is_file()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("appids", nargs="*", type=int, help="limit to these server app ids")
    ap.add_argument("--dir", default=str(DEFAULT_BASE), help="install base dir")
    a = ap.parse_args()

    base = Path(a.dir)
    wanted = a.appids or sorted(profiles.PROFILES)
    rows = [check(i, profiles.PROFILES[i], base)
            for i in wanted if i in profiles.PROFILES]

    missing = [r for r in rows if r["state"] == "MISSING"]
    installed = [r for r in rows if r["state"] != "not installed"]

    print(f"\nBase dir: {base}   profiles: {len(rows)}   installed: {len(installed)}\n")
    print(f"{'GAME':<26}{'RUNNER':<9}{'STATE':<12}DECLARED BINARY")
    print("-" * 94)
    for r in sorted(rows, key=lambda x: (x["state"] != "MISSING", x["game"].lower())):
        if r["state"] == "not installed":
            continue
        print(f"{r['game'][:24]:<26}{r['runner']:<9}{r['state']:<12}{r['declared'] or '-'}")

    for r in missing:
        print(f"\n  {r['game']}: '{r['declared']}' not found under {r['detail']}")
        if r.get("candidates"):
            print("    candidates:")
            for c in r["candidates"]:
                print(f"      {c}")
        else:
            print("    no plausible executables found — is the install complete?")

    gaps = []
    for i in wanted:
        if i in profiles.PROFILES:
            for rel in check_configs(i, profiles.PROFILES[i], base):
                gaps.append(f"{profiles.PROFILES[i]['game']}: {rel}")
    if gaps:
        print("\nConfig templates declared but not shipped:")
        for g in gaps:
            print(f"  {g}")

    skipped = len(rows) - len(installed)
    print(f"\n{len(missing)} wrong path(s), {skipped} not installed yet.")
    if missing:
        print("Fix the 'linux'/'windows' value in steam/profiles.py for each one above.")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
