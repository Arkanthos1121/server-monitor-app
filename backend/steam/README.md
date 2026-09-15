# Steam dedicated-server scan

Finds which games in a Steam library can run a **dedicated server**, and tells you
how to host each one.

## Quick scan (no app, no database)

```bash
cd backend/steam
python3 scanner.py --key <STEAM_API_KEY> --steamid <YOU> --deep
```

- `--key` — personal key from <https://steamcommunity.com/dev/apikey> (any domain works).
  You can also export `STEAM_API_KEY` instead of passing it.
- `--steamid` — a SteamID64, a full profile URL, or a vanity name; all three are resolved.
- `--deep` — also probe Steam's app metadata for games outside the catalog. Slower,
  but catches servers the curated list doesn't know about yet.

No credentials to hand? Match a pasted list of game names instead:

```bash
python3 scanner.py --names my-games.txt
```

Add `--json` to pipe the report somewhere else.

> The public-profile scrape that older tools used no longer returns game data —
> Steam serves an HTML shell for it. The Web API key is the only reliable path,
> and it works even when the profile is private.

## How detection works

Two signals, strongest first:

| Signal | Meaning | Confidence |
|---|---|---|
| `catalog` | The game is in `catalog.json`, which pairs it with a real dedicated-server app | High — every entry verified against live Steam data |
| `appinfo` | The game exposes `extended.serverbrowsername`, so it registers with Steam's master server browser | High precision, partial recall |

Neither signal guesses. A game with no signal is reported as unmatched rather than
assumed to be single-player.

### Why both are needed

`serverbrowsername` had **zero false positives** across the validation set, but it
misses servers that don't use Steam's browser — Palworld, Satisfactory, Terraria and
Euro Truck Simulator 2 all have dedicated servers and none of them set it. The
catalog covers those.

## Rebuilding the catalog

`catalog.json` is generated, not hand-written. `candidates.py` holds *unverified*
game → server-app pairs; `build_catalog.py` checks each one against live Steam
appinfo and drops anything that doesn't hold up:

```bash
python3 build_catalog.py
```

Need an appid while editing `candidates.py`?

```bash
python3 find_appid.py "Abiotic Factor" "Soulmask"
```

It rejects a pair when the server app doesn't exist, is hidden, isn't a server, or
has a name unrelated to the game. That check matters — it caught a wrong appid that
resolved to a completely different game's server, and several where the *game*
appid was wrong. Re-run it after editing `candidates.py`; a pair that fails
verification should be fixed or dropped, never forced through.

Current catalog: **78 verified entries** (69 with a separate SteamCMD server app,
9 whose server ships inside the game).
