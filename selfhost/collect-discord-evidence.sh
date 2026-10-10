#!/usr/bin/env bash
# Gather everything needed to diagnose the Discord bot into ONE pasteable file.
#
#   cd /opt/server-monitor-app/selfhost && bash collect-discord-evidence.sh
#
# Prints the path at the end. Secrets are reported as set/empty and by length
# only - no value from .env is ever written to the report.
set -uo pipefail

OUT="${TMPDIR:-/tmp}/discord-evidence-$(date +%Y%m%d-%H%M%S).txt"
cd "$(dirname "$0")" || exit 1

# docker compose v2 (plugin) or the old v1 binary.
if docker compose version >/dev/null 2>&1; then DC=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then DC=(docker-compose)
else echo "docker compose not found - is Docker installed?" >&2; exit 1; fi

section() { printf '\n===== %s =====\n' "$1"; }

{
  echo "collected $(date -Is) on $(hostname)"
  echo "compose: ${DC[*]}"

  section "containers"
  "${DC[@]}" ps 2>&1

  section "which variables are set (names and lengths only, no values)"
  # Read from the running container so this reflects what the app actually got,
  # not what .env says. A var set in .env but not passed through shows as empty.
  "${DC[@]}" exec -T backend python3 -c '
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
' 2>&1

  section ".env keys present on disk (names only)"
  if [ -f .env ]; then
    grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' .env | tr -d '=' | sort | tr '\n' ' '
    echo
    echo "(empty values:) $(grep -cE '^[A-Za-z_][A-Za-z0-9_]*=$' .env) of $(grep -cE '^[A-Za-z_][A-Za-z0-9_]*=' .env)"
  else
    echo "NO .env FILE - that alone disables the bot"
  fi

  section "backend log, discord lines only"
  "${DC[@]}" logs backend --tail 400 2>&1 | grep -i discord || echo "(no discord lines in the last 400 - the bot never started)"

  section "backend log, errors"
  "${DC[@]}" logs backend --tail 200 2>&1 | grep -iE 'error|traceback|exception' | tail -40 || echo "(none)"

  section "diagnose_discord.py"
  timeout 180 "${DC[@]}" exec -T backend python3 diagnose_discord.py 2>&1
  echo "(diagnostic exit: $?)"
} > "$OUT" 2>&1

echo
echo "Report written to: $OUT"
echo "Paste its contents back. It contains no passwords or tokens."
echo
echo "----- first 40 lines -----"
head -40 "$OUT"
