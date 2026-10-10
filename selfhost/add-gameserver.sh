#!/usr/bin/env bash
# Register a game server so the Discord bot has something to /start.
#
#   bash add-gameserver.sh                        # list what you can host
#   bash add-gameserver.sh <name> <game>
#   bash add-gameserver.sh valheim-main Valheim
#
# <name> is what you type in Discord. <game> is matched case-insensitively
# against any part of a title in the verified catalog.
set -uo pipefail
cd "$(dirname "$0")" || exit 1

# The API as seen from INSIDE the container, where these python snippets run.
API="${API:-http://localhost:8001/api}"

# docker compose exec does not forward the caller's environment, so anything
# the snippet needs has to be passed with -e explicitly.
dexec() {
  local envs=(-e "API=$API")
  while [ "${1:-}" = "-e" ]; do envs+=(-e "$2"); shift 2; done
  docker compose exec -T "${envs[@]}" backend "$@" </dev/null
}

CATALOG_PY='
import json, sys
from steam import profiles
want = sys.argv[1].lower()
entries = [e for e in json.load(open("steam/catalog.json"))["entries"] if e.get("ok")]
hits = [e for e in entries if want in e["game_name"].lower()]
exact = [e for e in hits if e["game_name"].lower() == want]
if exact:
    hits = exact
if not hits:
    print("NONE"); raise SystemExit
if len(hits) > 1:
    print("MANY")
    for e in hits[:15]:
        print("   ", e["game_name"])
    raise SystemExit
e = hits[0]
p = profiles.get(e["server_appid"]) or {}
print("HIT", e["game_appid"], e["server_appid"], p.get("port") or 0,
      p.get("players") or 0, e["game_name"], sep="\t")
'

LIST_PY='
import json
from steam import profiles
entries = {e["server_appid"]: e for e in json.load(open("steam/catalog.json"))["entries"]
           if e.get("ok")}
ready = sorted((e["game_name"], profiles.PROFILES[sid]["port"])
               for sid, e in entries.items() if sid in profiles.PROFILES)
for n, port in ready:
    print(f"   {n:<38} default port {port}")
print(f"\n   {len(ready)} ready to install; "
      f"{len(entries) - len(ready)} more verified but without a launch profile yet.")
'

NAME="${1:-}"
GAME="${2:-}"

if [ -z "$NAME" ] || [ -z "$GAME" ]; then
  echo "usage: bash add-gameserver.sh <name-for-discord> <game>"
  echo "e.g.:  bash add-gameserver.sh valheim-main Valheim"
  echo
  echo "Games with a launch profile:"
  dexec python3 -c "$LIST_PY" || {
    echo "Could not reach the backend. Check: docker compose ps"; exit 1; }
  exit 0
fi

found="$(dexec python3 -c "$CATALOG_PY" "$GAME")"
read -r tag appid sappid port players title <<<"$(printf '%s' "$found" | head -1)"
case "$tag" in
  HIT) ;;
  NONE) echo "No verified dedicated server matches '$GAME'."
        echo "Run with no arguments to see the list."; exit 1;;
  MANY) echo "'$GAME' matches several games - be more specific:"
        printf '%s\n' "$found" | tail -n +2; exit 1;;
  *)    echo "Could not read the catalog. Is the backend up?  docker compose ps"
        printf '%s\n' "$found" | head -5; exit 1;;
esac

echo "Matched: $title  (game $appid, server $sappid, default port $port)"
echo

# --------------------------------------------------------------- login ----
EMAIL="$(sed -n 's/^DISCORD_OWNER_EMAIL=//p' .env | head -1 | sed 's/[[:space:]]#.*$//' | xargs)"
read -r -p "WebminPulse email [${EMAIL}]: " entered
EMAIL="${entered:-$EMAIL}"
read -r -s -p "Password for $EMAIL: " PASSWORD; echo
[ -n "$PASSWORD" ] || { echo "No password given."; exit 1; }

TOKEN="$(dexec -e "EM=$EMAIL" -e "PW=$PASSWORD" python3 -c '
import json, os, urllib.request, urllib.error
body = json.dumps({"email": os.environ["EM"], "password": os.environ["PW"]}).encode()
req = urllib.request.Request(os.environ["API"] + "/auth/login", body,
                             {"Content-Type": "application/json"})
try:
    print(json.load(urllib.request.urlopen(req, timeout=20))["token"])
except urllib.error.HTTPError as e:
    print("ERR", e.code, e.read().decode()[:200])
except Exception as e:
    print("ERR 0", e)
' 2>&1 | tail -1)"

case "$TOKEN" in
  ERR*) echo "Login failed: $TOKEN"
        echo "No account yet? Register one in the app at http://localhost:8001 first."
        exit 1;;
  "")   echo "Login returned nothing - is the backend healthy?  docker compose ps"; exit 1;;
esac
echo "Logged in."

read -r -s -p "Password players use to join (blank = none): " GAMEPW; echo

# ------------------------------------------------------------ register ----
dexec -e "NAME=$NAME" -e "TITLE=$title" -e "TOKEN=$TOKEN" -e "GPW=$GAMEPW" \
      -e "APPID=$appid" -e "SAPPID=$sappid" -e "PORT=$port" -e "PLAYERS=$players" \
      python3 -c '
import json, os, urllib.request, urllib.error
payload = {"name": os.environ["NAME"], "game_appid": int(os.environ["APPID"]),
           "game_name": os.environ["TITLE"], "server_appid": int(os.environ["SAPPID"])}
if int(os.environ["PORT"]):    payload["port"] = int(os.environ["PORT"])
if int(os.environ["PLAYERS"]): payload["max_players"] = int(os.environ["PLAYERS"])
if os.environ["GPW"]:          payload["server_password"] = os.environ["GPW"]
req = urllib.request.Request(os.environ["API"] + "/gameservers",
                             json.dumps(payload).encode(),
                             {"Content-Type": "application/json",
                              "Authorization": "Bearer " + os.environ["TOKEN"]})
try:
    r = json.load(urllib.request.urlopen(req, timeout=30))
    print("Registered:", r.get("name"), "| port", r.get("port"), "| status", r.get("status"))
except urllib.error.HTTPError as e:
    print("Failed:", e.code, e.read().decode()[:300]); raise SystemExit(1)
'
rc=$?
if [ "$rc" -eq 0 ]; then
  echo
  echo "Next, in Discord:"
  echo "  /servers           - should now list $NAME"
  echo "  /install $NAME     - downloads the server files (can take a long while)"
  echo "  /start $NAME       - brings it up"
fi
exit "$rc"
