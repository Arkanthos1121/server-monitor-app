#!/usr/bin/env bash
# Repair JWT_SECRET and SERVER_ENC_KEY in selfhost/.env.
#
#   cd /opt/server-monitor-app/selfhost && bash fix-env-keys.sh
#
# Safe to run more than once:
#   - .env is backed up first, with a timestamp
#   - a value that is already valid is left exactly as it is
#   - SERVER_ENC_KEY is recovered from an older container when possible,
#     because a new one cannot decrypt what the old one encrypted
set -uo pipefail
cd "$(dirname "$0")" || exit 1

[ -f .env ] || { echo "No .env here. Run: cp -n .env.example .env"; exit 1; }

# Values as the app sees them: inline comment stripped, whitespace trimmed.
getval() { sed -n "s/^$1=//p" .env | head -1 | sed 's/[[:space:]]#.*$//' | xargs 2>/dev/null; }

valid_fernet() {
  [ "${#1}" -eq 44 ] && printf '%s' "$1" | grep -qE '^[A-Za-z0-9_-]{43}=$'
}

# A Fernet key is 32 random bytes, base64url-encoded. No Python needed.
gen_fernet() { head -c 32 /dev/urandom | base64 | tr '+/' '-_' | tr -d '\n'; }

setval() {
  local k="$1" v="$2"
  if grep -qE "^$k=" .env; then
    # | as the delimiter: base64url contains no |, but may contain / and =
    sed -i "s|^$k=.*|$k=$v|" .env
  else
    printf '%s=%s\n' "$k" "$v" >> .env
  fi
}

BACKUP=".env.backup-$(date +%Y%m%d-%H%M%S)"
cp -p .env "$BACKUP"
echo "Backed up .env -> $BACKUP"
echo

changed=0

# ---------------------------------------------------------- SERVER_ENC_KEY --
enc="$(getval SERVER_ENC_KEY)"
if valid_fernet "$enc"; then
  echo "[ok]      SERVER_ENC_KEY is already a valid Fernet key - left alone."
else
  # NB: ${v:-x} expands to v's VALUE when v is set, not to x. Using it here
  # printed the secret to the terminal. Describe it; never echo it.
  if [ -z "$enc" ]; then why="empty"; else why="invalid (${#enc} chars)"; fi
  echo "[PROBLEM] SERVER_ENC_KEY is $why - this is what"
  echo "          stops the backend booting."
  echo "          Searching older containers for the previous key..."
  found=""
  for id in $(docker ps -a --filter name=backend --format '{{.ID}}' 2>/dev/null); do
    v=$(docker inspect "$id" --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
        | sed -n 's/^SERVER_ENC_KEY=//p' | head -1)
    if valid_fernet "$v"; then found="$v"; echo "          recovered from container $id"; break; fi
  done
  if [ -n "$found" ]; then
    setval SERVER_ENC_KEY "$found"
    echo "[ok]      Restored the ORIGINAL key. Stored passwords stay readable."
  else
    setval SERVER_ENC_KEY "$(gen_fernet)"
    echo "[ok]      No old key found; generated a new one."
    echo "          Any Webmin passwords saved in the app must be re-entered."
  fi
  changed=1
fi

# -------------------------------------------------------------- JWT_SECRET --
jwt="$(getval JWT_SECRET)"
if [ "${#jwt}" -ge 32 ]; then
  echo "[ok]      JWT_SECRET is set (${#jwt} chars) - left alone."
else
  setval JWT_SECRET "$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  if [ -z "$jwt" ]; then why="empty"; else why="too short (${#jwt} chars, need 32+)"; fi
  echo "[ok]      JWT_SECRET was $why; generated a new one."
  echo "          Everyone signed in to the app will have to log in again."
  changed=1
fi

echo
if [ "$changed" -eq 0 ]; then
  echo "Nothing needed changing. If the backend still will not boot, the cause"
  echo "is something else - check: docker compose logs backend --tail 40"
  exit 0
fi

echo "Rebuilding..."
docker compose up -d --build </dev/null 2>&1 | tail -5
echo
echo "Waiting 15s for the backend to settle..."
sleep 15
docker compose ps </dev/null
echo
echo "===== backend log ====="
docker compose logs backend --tail 25 </dev/null 2>&1
