"""Look up Steam appids by game name, for maintaining candidates.py.

    python3 find_appid.py "Abiotic Factor" "Soulmask"

Only store-visible apps are searchable; dedicated-server tool apps are hidden
from this endpoint, so use it for the GAME appid and let build_catalog.py verify
the server appid you pair with it.
"""
import json
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

SEARCH = "https://steamcommunity.com/actions/SearchApps/"


def search(name: str):
    try:
        req = urllib.request.Request(SEARCH + urllib.parse.quote(name),
                                     headers={"User-Agent": "WebminPulse-SteamScan/1.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            return name, [(a["appid"], a["name"]) for a in json.load(r)[:5]]
    except Exception as e:
        return name, [("ERR", str(e))]


def main() -> int:
    names = sys.argv[1:]
    if not names:
        print(__doc__)
        return 2
    with ThreadPoolExecutor(8) as ex:
        for name, hits in ex.map(search, names):
            print(f"\n{name}:")
            for appid, found in hits or [("-", "no match")]:
                print(f"    {appid:<10} {found}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
