#!/usr/bin/env bash
# Rebuild, then diagnose. Use this rather than calling the script directly:
# the image bakes the code in, so `git pull` alone leaves the old copy running.
#
#   cd /opt/server-monitor-app/selfhost && bash diagnose.sh
set -uo pipefail
cd "$(dirname "$0")" || exit 1

echo "Rebuilding so the container has the current code..."
docker compose up -d --build </dev/null 2>&1 | tail -4
echo
echo "Waiting for the backend..."
for _ in $(seq 1 30); do
  state=$(docker compose ps --format '{{.Service}} {{.State}}' </dev/null 2>/dev/null | awk '$1=="backend"{print $2}')
  [ "$state" = "running" ] && break
  sleep 1
done
[ "${state:-}" = "running" ] || {
  echo "The backend is not running (state: ${state:-unknown}). Its log:"
  docker compose logs backend --tail 30 </dev/null 2>&1
  exit 1
}
echo
timeout 240 docker compose exec -T backend python3 diagnose_discord.py </dev/null
