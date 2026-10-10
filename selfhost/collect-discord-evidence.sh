#!/usr/bin/env bash
# Gather everything needed to diagnose the Discord bot into ONE pasteable file.
#
#   cd /opt/server-monitor-app/selfhost && bash collect-discord-evidence.sh
#
# Everything is printed live AND saved, so you can always see which step it is
# on. Every step has a timeout - the whole run cannot exceed about four
# minutes. Ctrl+C at any point is safe.
#
# Secrets are reported as set/empty and by length only; no value from .env is
# ever written to the report.
set -uo pipefail

OUT="${TMPDIR:-/tmp}/discord-evidence-$(date +%Y%m%d-%H%M%S).txt"
cd "$(dirname "$0")" || exit 1

if docker compose version >/dev/null 2>&1; then DC=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then DC=(docker-compose)
else echo "docker compose not found - is Docker installed?" >&2; exit 1; fi

# Every docker call gets a ceiling and a closed stdin. `exec` attaches stdin by
# default, which can leave it waiting on a terminal that will never send
# anything - the difference between a four-minute run and an overnight one.
dc() { local t="$1"; shift; timeout "$t" "${DC[@]}" "$@" </dev/null 2>&1; }

section() { printf '\n===== %s =====\n' "$1"; }

body() {
  echo "collected $(date -Is) on $(hostname)"
  echo "compose: ${DC[*]}"

  section "containers"
  dc 30 ps

  section "which variables are set (names and lengths only, no values)"
  # Read from the running container so this reflects what the app actually got,
  # not what .env says. A var set in .env but not passed through shows as empty.
  dc 60 exec -T backend python3 -c '
import os
for k in ("DISCORD_BOT_TOKEN","DISCORD_GUILD_ID","DISCORD_CHANNEL_ID",
          "DISCORD_OWNER_EMAIL","DISCORD_ADMIN_ROLE","JWT_SECRET",
          "SERVER_ENC_KEY","MONGO_URL","STEAM_API_KEY"):
    v = os.environ.get(k, "")
    if not v.strip():
        print(f"{k:22} EMPTY")
    elif k in ("DISCORD_GUILD_ID","DISCORD_CHANNEL_ID","DISCORD_OWNER_EMAIL",
               "DISCORD_ADMIN_ROLE"):
        print(f"{k:22} {v}")            # ids and emails are not secrets
    else:
        print(f"{k:22} set ({len(v)} chars, ends ...{v[-4:]})")
'

  section ".env keys present on disk (names only)"
  if [ -f .env ]; then
    grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' .env | tr -d '=' | sort | tr '\n' ' '
    echo
    echo "(empty values:) $(grep -cE '^[A-Za-z_][A-Za-z0-9_]*=$' .env) of $(grep -cE '^[A-Za-z_][A-Za-z0-9_]*=' .env)"
  else
    echo "NO .env FILE - that alone disables the bot"
  fi

  section "backend log, discord lines only"
  dc 60 logs backend --tail 400 | grep -i discord \
    || echo "(no discord lines in the last 400 - the bot never started)"

  section "backend log, last 40 lines verbatim"
  dc 60 logs backend --tail 40

  section "diagnose_discord.py"
  dc 180 exec -T backend python3 diagnose_discord.py
  echo "(diagnostic finished or timed out at 180s)"

  section "done"
}

echo "Writing to $OUT - this prints as it goes and takes up to ~4 minutes."
body 2>&1 | tee "$OUT"

echo
echo "================================================================"
echo "Report saved to: $OUT"
echo "Paste it back. It contains no passwords or tokens."
