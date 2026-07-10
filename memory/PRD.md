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
