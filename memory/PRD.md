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
