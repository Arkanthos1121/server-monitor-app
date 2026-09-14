# WebminPulse — PRD

## Original Problem Statement
Mobile app to monitor multiple Webmin servers. Home page shows status of every server; tap a
server to open its Webmin panel. Push a notification when a server is offline. Also review each
Webmin panel and notify when CPU or RAM > 85%, and query each Webmin for available package
updates and notify. (User asked to pause and check in at ~50 credits.)

## User Choices
- Connection: recommended → Webmin username/password over HTTPS:10000 (self-signed OK).
- Servers added manually in-app.
- Background poll interval: 30 minutes.
- Auth: both Google login (Emergent-managed) AND email/password (JWT).
- Design: futuristic (Dark-First cyber-ops command center).

## Architecture
- Frontend: Expo Router (SDK 54), react-native-svg gauges, reanimated, keyboard-controller,
  expo-notifications, react-native-webview. Theme in `src/theme/theme.ts`. Fonts: Rajdhani,
  Space Grotesk, IBM Plex Mono (local TTFs in assets/fonts).
- Backend: FastAPI + MongoDB (motor). JWT + Google session auth. httpx Webmin client
  (verify=False). Async background poller. Emergent push relay.
- Webmin data source: reachability via HTTPS GET; live stats via Authentic-Theme
  `/authentic-theme/stats.cgi?xhr-stats=general` (CPU/RAM/disk/load); updates via best-effort
  parse of `/package-updates/`.

## Implemented (2026-07-10)
- Auth: register/login (email+pw, bcrypt+JWT), Google OAuth (Emergent), /auth/me, settings.
- Server CRUD (per-user), immediate check on add, check-one, check-all (pull-to-refresh).
- Dashboard, Server Detail (gauges + sticky Open Webmin), Alerts, Settings.
- Background poller with alert transitions: offline/online, CPU>threshold, RAM>threshold, updates.
- Push endpoints + client registration + tap handlers.
- Webmin passwords encrypted at rest (Fernet).

## Implemented — Feature Update (2026-07-10, session 2)
- Historical telemetry: `db.metrics` samples CPU/RAM/disk on every check (7-day TTL). New
  `GET /api/servers/{id}/history?limit=` endpoint. Server Detail renders CPU% / RAM% SVG
  sparklines (Sparkline component) with "Collecting data…" empty state.
- Per-server alert toggle: `alerts_enabled` field on each server; toggle on Server Detail;
  `evaluate_and_alert` respects both user-level and server-level flags.
- Configurable poll interval: `user.poll_interval_minutes` (5/15/30/60) via segmented control in
  Settings; poller now wakes every 60s and checks each server when its user's interval elapses.
- iPhone 17 / iOS 26: Expo SDK 54 (iOS 26 compatible), safe-area insets throughout. Runs in Expo
  Go now; standalone build via Publish for push + self-signed WebView.

## Verified
- Backend curl: register/login/me, add server (offline detection ~10s), check-all, wrong-pw 401, alerts.
- Frontend (web preview): login render, register→dashboard redirect, add server→offline card.

## Backlog / Next
- P0: Run full `testing_agent` QA pass (backend + frontend e2e).
- P0 (needs build): Validate push notifications on real iOS/Android build (offline/CPU/RAM/updates).
  Requires Publish → deploy → generate build. Android also needs `google-services.json`.
- P1: Encrypt stored Webmin passwords at rest (currently plaintext in Mongo, never returned in API).
- P1: Configurable poll interval per user; per-server enable/disable alerts.
- P2: Historical charts (CPU/RAM over time), disk/network detail, biometric app lock, group/tags.

## Known Limitations
- Webmin has no official REST API; CPU/RAM/updates depend on Authentic Theme being installed and
  reachable. Updates count is best-effort HTML parsing. Online/offline detection is robust.
- Push notifications & in-app WebView of self-signed panels only fully testable on a real build.


## Security & Quality Hardening (2026-07-11, session 3)
- Security fixes: strong random JWT_SECRET; SSRF guard (blocks loopback/link-local/cloud-metadata/
  IPv4-mapped-IPv6/multicast/reserved, ALLOWS private LANs by design); authenticated
  /api/register-push (user_id from token); login brute-force throttle (5/300s -> 429); password
  min-length 8; Fernet-encrypted Webmin passwords; per-server verify_cert TLS option (default off);
  generic error strings (no exception leakage).
- Code-review fixes: global 401 handler -> auto-logout to /login; dashboard/detail/settings
  error+retry states; concurrent poller (semaphore=10); update-alerts only on count increase;
  settings controls re-sync from user; per-server toggle rollback on failure.
- Metrics fallback: modern Authentic Theme stats.cgi returns a websocket handle, so CPU/RAM/load
  are also scraped from the Running Processes (/proc) module.
- Testing iteration 2: 28/28 backend + all frontend flows PASSED. Bottom-tab height fixed.
- Residual: in-memory login throttle is per-process (use shared store when scaling to N workers).


## Check Modes + Self-Host Kit (2026-07-11, session 4)
- Check modes per server: check_mode = "webmin" (HTTP, full metrics + auth_ok detection),
  "tcp" (port-open via asyncio.open_connection), "ping" (ICMP via ping subprocess; needs NET_RAW +
  ICMP allowed — blocked in cloud sandbox, works on LAN). Username/password now optional (only
  required for webmin). Detail hides gauges/history/updates for non-webmin and shows CHECK MODE +
  AUTH lines; cards show PORT OPEN / PING OK / OFFLINE + an AUTH-FAILED badge for webmin 401s.
  Verified: TCP 8.8.8.8:53 online, :9 offline; UI selector + card states.
- Self-host kit at /app/selfhost/ (docker-compose.yml: mongo:7 + inline-Dockerfile backend +
  NET_RAW; .env.example; README.md): run backend+Mongo on a Raspberry Pi 5 to reach LAN Webmin;
  Cloudflare Tunnel for remote access; point app via EXPO_PUBLIC_BACKEND_URL.
- PUSH (support-confirmed): Emergent-managed push is tied to Emergent's build/deploy pipeline and
  NOT confirmed for a self-hosted backend. Fully self-hosted push = switch to Expo push tokens +
  Expo push service (FCM/APNs) [next step]. Fixed bottom-tab label clipping.
## Code Review Fixes (2026-07-11, session 5)
- MEDIUM fixed: (1) POLL_INTERVAL_SECONDS now seeds DEFAULT_POLL_MIN used for new-user default +
  poller fallback (env knob is effective); (2) /api/servers/check-all now bounded by
  Semaphore(10) like the poller; (3) PUT /api/servers/{id} now re-checks immediately
  (check_server + evaluate + record_metric) so a corrected server updates right away.
- LOW fixed: server-side check_mode validation (400 on invalid); Settings "Saved ✓" resets when a
  control changes; add-form requires password when switching a node INTO webmin mode (even on edit);
  detail offline banner is now mode-aware (ping/tcp/webmin). Verified via curl + UI screenshot.
- Residual (accepted): in-memory login throttle is per-process; CORS wildcard (security-only);
  webmin auth_ok=status!=401 may not catch 200-login-page auth failures (fleet-dependent).

## Steam Dedicated Servers + Discord Control (2026-09-13, session 6)
- User ask: "scan my steam library for every game that can have a dedicated server", then
  "start any server from a Discord channel" and "stop after 12 hours unless a command says otherwise".
- Steam scan (`backend/steam/`): `scanner.py` reads owned games via Web API key
  (GetOwnedGames; resolves SteamID64 / profile URL / vanity name) or matches a pasted name
  list. Two detection signals: the verified catalog, and `extended.serverbrowsername` from
  appinfo (`--deep`). The old public-profile XML scrape is dead (Steam returns an HTML shell),
  so the API key is the only reliable library source — documented as such.
- Catalog (`backend/steam/catalog.json`, 78 entries) is GENERATED by `build_catalog.py`, which
  verifies every candidate pair in `candidates.py` against live Steam appinfo and drops
  mismatches. This caught a wrong server appid resolving to an unrelated game's server, plus
  several wrong game appids. Never hand-edit catalog.json.
- Game servers (`backend/gameservers.py`, `gameserver_service.py`, `steam/profiles.py`):
  SteamCMD install, subprocess launch with 21 per-game launch profiles, graceful
  SIGTERM→SIGKILL stop, PID + /proc start-tick tracking so a backend restart re-attaches
  instead of showing phantom "running".
- 12h rule: start sets `auto_stop_at` = now + GAMESERVER_AUTO_STOP_HOURS (12). `reaper_loop`
  runs every 60s, warns in Discord 15 min out, then stops. `/extend` is relative to NOW and
  clamped to 24h; `/keepalive` exempts entirely. All start/stop/extend audited to
  `gameserver_events` with the actor.
- Discord bot (`backend/discord_bot.py`, in-process, optional via DISCORD_BOT_TOKEN):
  `/servers /start /stop /extend /keepalive /install` with name autocomplete and an optional
  role gate. Shares gameserver_service with the REST API so both surfaces obey the same rules.
- API: POST/GET `/api/steam/scan`, CRUD + start/stop/extend/keepalive/install under
  `/api/gameservers`.
- Tests: 33 passing (`tests/test_gameservers.py`, `tests/test_gameserver_service.py`) covering
  the 12h boundary, extend-saves-from-reaper, keepalive, PID reuse, audit trail, reconcile.

- Split topology (user runs a separate GAMESERVER box, not the Pi): gameservers.py can drive
  a remote host over SSH. GAMESERVER_SSH_HOST blank = local subprocesses; set = install/start/
  stop run on that box. Servers launched with setsid so they survive backend restarts and
  dropped SSH connections; remote stop mirrors the SIGTERM->SIGKILL grace locally.
  15 tests cover argv construction, PID capture, and both terminate paths.

### Known Limitations
- SteamCMD and dedicated servers are x86_64-only: the hosting half does NOT run on a Pi.
  Scan/catalog/API/bot are fine on ARM. Use GAMESERVER_SSH_HOST to reach an x86_64 box.
- Remote mode drops the /proc start-tick check (pid_start_ticks is local-only), so remote
  PID-reuse detection is weaker than local. Acceptable: setsid PIDs are long-lived.
- The bot acts as ONE WebminPulse account (DISCORD_OWNER_EMAIL). No per-Discord-user linking.
- Launch profiles cover 21 popular servers; other games need `launch_cmd` set explicitly.
- Catalog is not exhaustive. Games with no verified server app and no `serverbrowsername`
  (Green Hell, Sunkenland, Deadside, Citadel, Myth of Empires, Reign of Kings, Dark and Light)
  are deliberately omitted rather than guessed at.
- Not yet run against a real Steam library, a live Discord guild, or a real SteamCMD install.
- Steam's community games page now returns a Sign In shell to datacenter IPs even for public
  profiles (verified against the user's own public profile, visibilityState 3, with a browser
  UA). There is NO credential-free way to read a library; the Web API key is required.

## Idle Shutdown, Save-on-Stop, Griefing Protection, Proton/Wine (2026-09-14, session 7)
- CORRECTION to session 6: auto-stop was uptime-based (12h after start). User clarified they want
  12h with NOBODY ONLINE. Rewritten around idle time; an occupied server is never reaped.
- `backend/a2s.py`: Steam A2S_INFO queries (UDP) incl. the modern challenge handshake. Bots are
  subtracted from the player count. CRITICAL invariant: an unreachable/non-A2S server returns
  None, never 0 — an unknown count must never be mistaken for empty or the reaper kills a live
  server. 11 tests, incl. live UDP round-trips against a local fake server.
- Idle model in gameservers.py: `empty_since` starts when the last player leaves and is cleared
  when anyone joins; repeated empty polls do NOT push it. `occupancy_patch()` is the single place
  that maps a poll result to persisted state. Unqueryable games (Palworld/Satisfactory use REST)
  fall back to uptime so they still stop eventually. `idle_grace_until` backs /extend.
- `backend/rcon.py`: Source RCON client. `save_then_stop()` sends the game's save command, waits
  for ack, then SIGTERM with a 120s grace (vs 30s) so large ARK/7DTD worlds finish flushing.
  save_cmd declared only for games that genuinely speak Source RCON (ARK SE/SA, 7DTD, Palworld);
  Rust is WebSocket RCON and SE has no console, so those rely on save-on-exit. A failed save
  never blocks a shutdown — it is reported.
- Griefing protection gated on OCCUPANCY, not roles (a role gate would have broken the legitimate
  ASA<->Space Engineers RAM swap): empty -> anyone stops it; occupied -> /stop refuses;
  /requeststop gives 5 min notice and ANY player can /keepplaying to veto; admin force:True is
  announced in-channel and audited as `force_stop` with the actor.
- Proton/Wine runners: `runner` field on profiles. Install passes
  `+@sSteamCmdForcePlatformType windows` (must precede +login); launch wraps the Windows binary
  with Proton (STEAM_COMPAT_DATA_PATH) or Wine (WINEPREFIX). ARK: Survival Ascended -> proton,
  Space Engineers -> wine.
- New Discord commands: /players /requeststop /keepplaying, /stop gains force. /servers shows
  occupancy. Reaper loop polls occupancy every 60s and executes un-vetoed stop requests.
- 101 tests passing across 6 files.

### Known Limitations
- A2S query ports are per-game guesses (game port +1 by default, +0 for Source). Verify per
  server; profiles can override with query_port.
- RCON save needs a password on the record (rcon_password/server_password); without one it falls
  back to SIGTERM save-on-exit.
- /keepplaying can be run by anyone in the channel, not only by people actually on the server —
  Discord identity is not linked to in-game identity. Acceptable for a friend group; would need
  per-game player-name lookup (A2S_PLAYER) to tighten.
- Proton/Wine paths are unverified against a real install (no x86_64 host in this session).
