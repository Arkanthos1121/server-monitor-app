"""Verify every candidate pair against live Steam appinfo and emit catalog.json.

Run:  python3 build_catalog.py
A pair is kept only if the server app really exists and its name plausibly
belongs to the game (or the server app is a known shared/multi-game server).
"""
import json, re, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor

from candidates import CANDIDATES

INFO = "https://api.steamcmd.net/v1/info/{}"
# GoldSrc HLDS (90) hosts many Valve games; its name never matches the game.
SHARED_SERVER_APPS = {90}
STOP = {"the", "a", "of", "and", "2", "ii", "dedicated", "server", "steam"}


def fetch(appid):
    try:
        with urllib.request.urlopen(INFO.format(appid), timeout=30) as r:
            return json.load(r)["data"][str(appid)]
    except Exception:
        return None


def tokens(name):
    return {t for t in re.split(r"[^a-z0-9]+", (name or "").lower()) if t and t not in STOP}


def name_matches(game_name, server_name):
    g, s = tokens(game_name), tokens(server_name)
    if not g or not s:
        return False
    return len(g & s) / len(g) >= 0.5


def check(item):
    game_appid, (hint, server_appid) = item
    g = fetch(game_appid)
    if not g:
        return {"game_appid": game_appid, "hint": hint, "ok": False, "why": "game appinfo unavailable"}
    gc = g.get("common", {}) or {}
    gext = g.get("extended", {}) or {}
    game_name = gc.get("name") or hint
    sbn = gext.get("serverbrowsername") or ""

    row = {
        "game_appid": game_appid, "game_name": game_name, "hint": hint,
        "server_browser_name": sbn, "server_appid": None, "server_name": None,
        "ok": False, "why": "", "signals": [],
    }
    if sbn:
        row["signals"].append("serverbrowsername")

    if server_appid is None:
        # Server binary ships inside the game itself; nothing separate to verify.
        row["ok"] = True
        row["why"] = "server ships with the game"
        row["signals"].append("bundled")
        row["bundled"] = True
        return row

    s = fetch(server_appid)
    if not s:
        row["why"] = f"server app {server_appid} appinfo unavailable"
        return row
    sc = s.get("common", {}) or {}
    sname = sc.get("name")
    if not sname:
        row["why"] = f"server app {server_appid} has no name (hidden/delisted)"
        return row
    row["server_appid"], row["server_name"] = server_appid, sname

    if server_appid in SHARED_SERVER_APPS:
        row["ok"] = True; row["why"] = "shared multi-game server app"
        row["signals"].append("shared_server_app")
        return row
    if not re.search(r"server", sname, re.I):
        row["why"] = f"app {server_appid} ('{sname}') is not a server app"
        return row
    if not name_matches(game_name, sname):
        row["why"] = f"name mismatch: game '{game_name}' vs server '{sname}'"
        return row

    row["ok"] = True; row["why"] = "verified"
    row["signals"].append("server_app")
    return row


def main():
    with ThreadPoolExecutor(12) as ex:
        rows = list(ex.map(check, CANDIDATES.items()))
    kept = sorted([r for r in rows if r["ok"]], key=lambda r: r["game_name"].lower())
    dropped = sorted([r for r in rows if not r["ok"]], key=lambda r: str(r["hint"]).lower())

    print(f"VERIFIED {len(kept)} / {len(rows)}\n")
    if dropped:
        print("DROPPED (failed verification):")
        for r in dropped:
            print(f"  - {r['hint']:<32} {r['why']}")
        print()
    json.dump({"generated_from": "api.steamcmd.net", "entries": kept},
              open("catalog.json", "w"), indent=1)
    print(f"wrote catalog.json with {len(kept)} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
