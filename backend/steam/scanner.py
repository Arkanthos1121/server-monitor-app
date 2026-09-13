"""Scan a Steam library and report which games can run a dedicated server.

Two detection signals, in order of confidence:
  1. catalog  - game appid is in catalog.json, whose every entry was verified
                against live Steam appinfo by build_catalog.py.
  2. appinfo  - the game exposes extended.serverbrowsername, meaning it
                registers with Steam's master server browser. Zero false
                positives across the validation set, but misses servers that
                don't use the Steam browser, which is why the catalog exists.

Usage:
    python3 scanner.py --key <STEAM_API_KEY> --steamid <STEAMID64> [--deep]
    python3 scanner.py --names games.txt          # no credentials needed
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CATALOG_PATH = Path(__file__).with_name("catalog.json")
API = "https://api.steampowered.com"
INFO = "https://api.steamcmd.net/v1/info/{}"
UA = {"User-Agent": "WebminPulse-SteamScan/1.0"}


def _get(url: str, timeout: int = 30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def load_catalog() -> dict:
    data = json.loads(CATALOG_PATH.read_text())
    return {int(e["game_appid"]): e for e in data["entries"]}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


# ----------------------------------------------------------------- library --
def resolve_steamid(api_key: str, who: str) -> str:
    """Accept a SteamID64, a full profile URL, or a vanity name."""
    who = who.strip().rstrip("/")
    m = re.search(r"/(?:profiles|id)/([^/]+)", who)
    if m:
        who = m.group(1)
    if re.fullmatch(r"\d{17}", who):
        return who
    url = f"{API}/ISteamUser/ResolveVanityURL/v1/?key={api_key}&vanityurl={urllib.parse.quote(who)}"
    r = _get(url).get("response", {})
    if r.get("success") != 1:
        raise SystemExit(f"Could not resolve '{who}' to a SteamID64 (is the vanity URL right?)")
    return r["steamid"]


def owned_games(api_key: str, steamid: str) -> list[dict]:
    url = (f"{API}/IPlayerService/GetOwnedGames/v1/?key={api_key}&steamid={steamid}"
           "&include_appinfo=1&include_played_free_games=1&format=json")
    resp = _get(url).get("response", {})
    if "games" not in resp:
        raise SystemExit(
            "Steam returned no games. Either the API key is wrong, or this profile's\n"
            "Game Details are not visible to that key. Set Steam > Privacy > Game details\n"
            "to Public, or use your own key with your own SteamID64."
        )
    return [{"appid": int(g["appid"]), "name": g.get("name", f"App {g['appid']}"),
             "playtime_min": g.get("playtime_forever", 0)} for g in resp["games"]]


def games_from_names(path: str, catalog: dict) -> list[dict]:
    """Fallback: match a pasted list of game names against the catalog."""
    by_norm = {_norm(e["game_name"]): a for a, e in catalog.items()}
    out = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        appid = by_norm.get(_norm(line))
        out.append({"appid": appid or 0, "name": line, "playtime_min": 0})
    return out


# ---------------------------------------------------------------- detection --
def probe_serverbrowsername(appid: int):
    try:
        d = _get(INFO.format(appid), timeout=30)["data"][str(appid)]
        ext = d.get("extended", {}) or {}
        com = d.get("common", {}) or {}
        return appid, ext.get("serverbrowsername") or "", com.get("type", "")
    except Exception:
        return appid, "", ""


def scan(games: list[dict], catalog: dict, deep: bool = False, workers: int = 12) -> dict:
    hits, unknown = [], []
    for g in games:
        e = catalog.get(g["appid"])
        if e:
            hits.append({**g,
                         "server_name": e.get("server_name"),
                         "server_appid": e.get("server_appid"),
                         "bundled": bool(e.get("bundled")),
                         "how": "catalog"})
        else:
            unknown.append(g)

    if deep and unknown:
        ids = [g["appid"] for g in unknown if g["appid"]]
        found = {}
        with ThreadPoolExecutor(workers) as ex:
            for appid, sbn, _t in ex.map(probe_serverbrowsername, ids):
                if sbn:
                    found[appid] = sbn
        still = []
        for g in unknown:
            if g["appid"] in found:
                hits.append({**g, "server_name": None, "server_appid": None,
                             "bundled": False, "how": "appinfo",
                             "server_browser_name": found[g["appid"]]})
            else:
                still.append(g)
        unknown = still

    hits.sort(key=lambda h: (-h["playtime_min"], h["name"].lower()))
    return {"total_games": len(games), "dedicated_capable": hits,
            "unmatched": len(unknown), "deep": deep}


# --------------------------------------------------------------------- CLI --
def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--key", default=os.environ.get("STEAM_API_KEY"),
                   help="Steam Web API key (or set STEAM_API_KEY)")
    p.add_argument("--steamid", help="SteamID64, profile URL, or vanity name")
    p.add_argument("--names", help="file of game names, one per line (no credentials)")
    p.add_argument("--deep", action="store_true",
                   help="also probe Steam appinfo for games outside the catalog")
    p.add_argument("--json", dest="as_json", action="store_true", help="emit JSON")
    a = p.parse_args()

    catalog = load_catalog()
    if a.names:
        games = games_from_names(a.names, catalog)
    elif a.key and a.steamid:
        games = owned_games(a.key, resolve_steamid(a.key, a.steamid))
    else:
        p.error("need --names, or both --key and --steamid")

    rep = scan(games, catalog, deep=a.deep)
    if a.as_json:
        print(json.dumps(rep, indent=1))
        return 0

    hits = rep["dedicated_capable"]
    print(f"\nScanned {rep['total_games']} games -> {len(hits)} can run a dedicated server\n")
    print(f"{'GAME':<38} {'PLAYED':>8}  HOW TO HOST")
    print("-" * 82)
    for h in hits:
        hrs = f"{h['playtime_min']/60:.0f}h" if h["playtime_min"] else "-"
        if h["bundled"]:
            how = "server ships with the game"
        elif h["server_appid"]:
            how = f"SteamCMD app {h['server_appid']}"
        else:
            how = "in-game server browser"
        print(f"{h['name'][:36]:<38} {hrs:>8}  {how}")
    print("-" * 82)
    print(f"{rep['unmatched']} games had no dedicated-server signal"
          + ("" if rep["deep"] else "  (re-run with --deep to probe them)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
