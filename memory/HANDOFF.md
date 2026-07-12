# WebminPulse — Agent Handoff / Continuity Document
_Last updated: 2026-07-11. Written by the building agent (E1) for any successor agent._

If you are taking over this project, READ THIS FIRST, then `PRD.md`, then `test_credentials.md`,
all in `/app/memory/`. This file is the "black box recorder": what the app is, how it works,
every non-obvious decision and why, the traps I hit, and what's left to do.

---

## 0. TL;DR
**WebminPulse** = a mobile app (Expo/React Native + FastAPI + MongoDB) that monitors multiple
**Webmin** servers (https://webmin.com). It shows each server's online/offline status + CPU/RAM,
lets you open the Webmin panel, and sends push notifications when a server goes offline / CPU or
RAM exceed a threshold / package updates are available.

Status: **Fully built, tested (28/28 backend + all frontend flows passed), security-audited and
code-reviewed twice each, all findings fixed.** Runs in the Emergent preview now. Push notifications
+ self-signed WebView require a real device build (not testable in Expo Go/web).

The user's end goal: **self-host the backend at home on a Raspberry Pi 5** so it can reach LAN
Webmin servers, and **receive push notifications while away from home.** (Self-host kit exists;
push-while-self-hosted is the main open question — see §9.)

---

## 1. Environment & platform (Emergent)
- Full-stack container: Expo (Metro) frontend on **:3000**, FastAPI backend on **:8001**, local MongoDB.
- Ingress: `/` → :3000, `/api/*` → :8001. **All backend routes MUST be prefixed `/api`.**
- Services managed by supervisor: `sudo supervisorctl restart backend|expo`.
  **ALWAYS restart expo before handing back to the user** (changes don't hot-reload reliably).
- Frontend calls backend via `process.env.EXPO_PUBLIC_BACKEND_URL` (already set; do NOT hardcode).
- PROTECTED — never edit: `frontend/.env` keys `EXPO_PACKAGER_PROXY_URL`/`EXPO_PACKAGER_HOSTNAME`,
  `backend/.env` `MONGO_URL`, `metro.config.js`, package.json `main`.
- Backend logs: `tail -n 100 /var/log/supervisor/backend.err.log`.
- Preview URL used for screenshots: the frontend origin (EXPO_PUBLIC_BACKEND_URL host).

### backend/.env (keys I added)
```
JWT_SECRET=<64-hex random>          # rotate for prod; deployment pipeline may override
SERVER_ENC_KEY=<Fernet key>         # encrypts stored Webmin passwords at rest
EMERGENT_PUSH_KEY=placeholder       # auto-injected by Emergent deploy pipeline; DO NOT hand-edit
POLL_INTERVAL_SECONDS=1800          # seeds DEFAULT_POLL_MIN (new-user default + poller fallback)
```

---

## 2. What the app does (features, all implemented)
1. **Auth**: email/password (bcrypt + HS256 JWT) AND Emergent-managed Google login (session token).
2. **Servers**: user adds servers manually (name, host, port, username, password, HTTPS, verify-cert,
   check_mode). Per-user isolation.
3. **Dashboard** (`/(tabs)/index`): 2-col grid, glowing online/offline dots, CPU/RAM bars (webmin
   mode) or PORT OPEN / PING OK (tcp/ping), updates badge, global "N NODES DOWN" summary, FAB, pull-
   to-refresh (→ check-all), error+retry state.
4. **Server detail** (`/server/[id]`): animated CPU/RAM/Disk gauges (SVG+reanimated), telemetry
   sparklines, uptime/load/last-check, CHECK MODE + AUTH lines, package updates, per-server alert
   toggle, sticky **Open Webmin Panel** (in-app WebView + browser fallback), edit/delete, error+retry.
5. **Alerts** (`/(tabs)/alerts`): incident log, severity colors, clear-all.
6. **Settings** (`/(tabs)/settings`): CPU/RAM thresholds (steppers), alerts toggle, poll interval
   (5/15/30/60 segmented), logout. Controls re-sync from user; "Saved ✓" resets on change.
7. **Check modes** (per server): `webmin` (HTTP login → online + CPU/RAM/updates + auth_ok),
   `tcp` (port-open), `ping` (ICMP). Credentials only required for webmin.
8. **Background poller**: every 60s wakes, checks each server whose owner's interval elapsed,
   raises alerts on transitions, records metrics, sends push. Concurrency via Semaphore(10).
9. **Push** (Emergent relay): register device token (authed), send on alerts. Needs a real build.

---

## 3. Backend architecture (`/app/backend/server.py`, single file)
- **Models** (Pydantic): SignupBody, LoginBody, GoogleBody, ServerBody, ServerUpdateBody,
  SettingsBody, RegisterPushBody.
- **Mongo collections**: `users`, `user_sessions` (google), `servers`, `alerts`, `metrics` (7-day TTL).
  IDs are `uuid4` strings in an `id`/`user_id` field (NOT Mongo `_id`; always project `{"_id":0}`).
- **Auth**: `get_current_user(Authorization: Bearer <token>)` tries JWT decode first, then falls back
  to `user_sessions.session_token` (Google). `public_user()` strips secrets.
- **Webmin client `check_server(srv)`**:
  - `validate_host_allowed(host)` (SSRF guard) → blocked hosts return early.
  - `mode=ping` → `ping_check()` (subprocess). `mode=tcp` → `tcp_check()` (asyncio.open_connection).
  - `mode=webmin` → httpx GET `/authentic-theme/stats.cgi?xhr-stats=general`
    (verify=srv.verify_cert, follow_redirects=False, timeout 10s, basic auth). Any response ⇒ online;
    `auth_ok = status != 401`. Then `_parse_stats(json)`; if cpu&ram still None → fallback scrape
    `/proc/` via `_parse_proc_html()` (regex CPU idle→used, Real memory used/total, load averages);
    then `/package-updates/` → `_count_updates()`.
- **Alerts**: `evaluate_and_alert(user, server, status)` fires on TRANSITIONS only (offline↔online,
  CPU/RAM crossing threshold, updates count INCREASE). Respects user.alerts_enabled AND
  server.alerts_enabled. `create_alert()` also calls `send_push()` (non-blocking, idempotency key).
- **Metrics**: `record_metric()` stores online samples with cpu/ram; `GET /servers/{id}/history`.
- **Poller** `poller_loop()`: 60s loop, per-user interval via `last_status.checked_at`, Semaphore(10).
- **Security helpers**: bcrypt hash/verify; JWT; Fernet enc/dec of passwords; login rate-limit
  (in-memory `_login_attempts`, 5/300s→429); password min length 8; `validate_host_allowed`.
- **Routes** (all `/api`): auth/register, auth/login, auth/google, auth/me, PUT settings;
  servers CRUD + `{id}/check` + check-all + `{id}/history`; alerts GET/DELETE; register-push (authed).

### Endpoint quick map
```
POST /api/auth/register {email,password,name?}   -> {token,user}   (pw>=8)
POST /api/auth/login    {email,password}          -> {token,user}   (rate-limited)
POST /api/auth/google   {session_id}              -> {token,user}
GET  /api/auth/me                                  -> user
PUT  /api/settings {cpu_threshold,ram_threshold,alerts_enabled,poll_interval_minutes}
POST /api/servers {name,host,port,username?,password?,use_ssl,verify_cert,check_mode}
GET  /api/servers ; GET/PUT/DELETE /api/servers/{id}
POST /api/servers/{id}/check ; POST /api/servers/check-all
GET  /api/servers/{id}/history?limit=
GET  /api/alerts ; DELETE /api/alerts
POST /api/register-push {platform,device_token}   (Authorization required; user_id from token)
```

---

## 4. Frontend architecture (Expo Router, `/app/frontend`)
Routes (`app/`): `_layout.tsx` (fonts+splash+push handlers+providers), `index.tsx` (auth gate),
`login.tsx`, `(tabs)/_layout.tsx` + `(tabs)/index.tsx|alerts.tsx|settings.tsx`,
`server/[id].tsx` (detail), `server/add.tsx` (add/edit modal), `webview.tsx` (modal).
Shared (`src/`): `context/AuthContext.tsx`, `lib/api.ts` (fetch client + global 401 handler +
types), `theme/theme.ts` (colors/spacing/fonts/`metricColor`), `components/`
(`Gauge`, `Sparkline`, `ServerCard`, `common` = StatusDot/Bar/NeonButton/Card/ScreenTitle).
- **Design**: futuristic dark "cyber-ops" (see `/app/design_guidelines.json`). Fonts loaded from
  `assets/fonts/` via expo-font: Rajdhani (display), Space Grotesk (body), IBM Plex Mono (mono).
- **Auth flow**: AuthContext bootstraps token→/me; login/register/google set token+user; global 401
  handler (`setUnauthorizedHandler`) clears token + `router.replace('/login')`. `login.tsx` redirects
  to `/(tabs)` when `user` set. Push registered on auth (native only).
- **Keyboard**: `react-native-keyboard-controller` (KeyboardProvider in `_layout`,
  KeyboardAwareScrollView + KeyboardStickyView in forms).
- Every interactive/informational element has a kebab-case `testID`.

---

## 5. Key decisions & WHY (don't "fix" these without understanding)
- **SSRF guard ALLOWS private LANs (10/8, 192.168/16, 172.16/12).** This is intentional — the app's
  whole point is monitoring internal Webmin boxes. It blocks loopback/link-local/`169.254.169.254`
  (cloud metadata)/IPv4-mapped-IPv6/multicast/reserved only. Do NOT block RFC1918.
- **`verify=False` default for Webmin TLS.** Webmin ships self-signed certs on :10000. Strict verify
  would break the core feature. Per-server `verify_cert` toggle lets users opt in when they have a
  valid cert (e.g. behind a Cloudflare Tunnel).
- **Metrics fallback via `/proc/` scrape.** BIG discovery: modern Authentic-Theme
  `stats.cgi?xhr-stats=general` returns a **WebSocket handle** (`{success,port,socket}`), NOT metrics
  JSON. So `_parse_stats` returns None on current Webmin, and we scrape the Running Processes module
  for CPU/RAM/load. `_parse_stats` is kept for older versions. **CPU/RAM accuracy is unverified
  against a real Webmin — I had no live server to test.** Online/offline is rock-solid regardless.
- **Alerts on transitions only** (no first-check-offline alert) to avoid spam.
- **In-memory login throttle** (not Redis) — fine for single-worker self-host; note for scaling.
- **Passwords stored Fernet-encrypted, never returned by API.**

---

## 6. TRAPS I hit (so you don't waste cycles)
- **File-tail duplication bug (hit TWICE):** editing large blocks near the end of `server.py` left
  duplicated/garbage lines after the CORS middleware, causing `IndentationError` on restart.
  → After big edits, `python3 -c "import ast; ast.parse(open('server.py').read())"` BEFORE relying on
  the reload, and check the last ~30 lines.
- **ICMP ping returns False in the Emergent preview** (outbound ICMP blocked / no CAP_NET_RAW). It
  works on the user's LAN/Pi (compose sets `cap_add: NET_RAW`). Don't "fix" ping based on preview.
- **Email validation rejects reserved TLDs** (`.test`, etc.) → use `@example.com` in tests.
- **Rotating JWT_SECRET invalidates existing tokens** — users must re-login (expected).
- **Parallel search_replace edits occasionally didn't all land** — after a batch, re-grep to confirm
  each change actually applied (I got bitten by a missing password-policy + helper insert).
- **Web preview shows `shadow*`/`pointerEvents` deprecation warnings** — cosmetic, web-only, ignore.

---

## 7. Test credentials (see also `/app/memory/test_credentials.md`)
- `ops@example.com` / `secret123` and others; register your own (pw ≥ 8, real-looking domain).
- Google login = Emergent-managed, no app password.
- Demo unreachable server for UI: host `10.255.255.1:10000` (shows OFFLINE — correct).
- Public TCP test: `8.8.8.8:53` (open) vs `8.8.8.8:9` (closed).

---

## 8. Self-host kit (`/app/selfhost/`)
`docker-compose.yml` (mongo:7 + backend via `dockerfile_inline`, `NET_RAW` for ping),
`.env.example`, `README.md` (Pi 5 + NVMe, Cloudflare Tunnel, point app via EXPO_PUBLIC_BACKEND_URL).
On Pi 3/4 use `mongo:4.4` (Pi 5's ARMv8.2 runs mongo:7).

---

## 9. OPEN QUESTIONS / what I'd do next (prioritized)
- **P0 — Push while self-hosted (the user's actual goal).** Support confirmed Emergent-managed push
  is tied to Emergent's build/deploy pipeline and is NOT confirmed to work from a self-hosted backend.
  **Recommended next task: migrate push from the Emergent relay to Expo push tokens + Expo push
  service (FCM/APNs)** so a self-hosted Pi backend can notify the phone. Touches: `AuthContext`
  (getExpoPushTokenAsync), backend `send_push`/`register_push` (call Expo's API), app.json (FCM/APNs
  creds via a real build). This is auth/integration-adjacent → call `integration_expert` first.
- **P1 — Verify CPU/RAM against a REAL Webmin** (Authentic Theme + /proc). The parsing is best-effort
  and untested on live data. Consider Webmin's RPC/remote API as a more reliable source.
- **P1 — Combined "TCP-then-Webmin" check mode** for instant offline detection (I suggested this to
  the user; they haven't confirmed).
- **P2 — Maintenance mode** (mute a node's alerts for 1h). Distinct "AUTH FAILED" already exists.
- **P2 — Disk/network gauges, longer history charts, per-node interval, biometric app lock.**
- **Residual security (accepted):** per-process login throttle; CORS wildcard; `auth_ok` only detects
  HTTP 401 (a Webmin that returns a 200 login page on bad creds won't be flagged).

---

## 10. How to verify quickly after a change
```
# backend syntax + restart + smoke
python3 -c "import ast; ast.parse(open('/app/backend/server.py').read())"
sudo supervisorctl restart backend && sleep 4 && tail -n 5 /var/log/supervisor/backend.err.log
# register/login/add/offline/tcp/ssrf via curl (see test_credentials.md for patterns)
# frontend
lint (ESLint) then restart expo, then screenshot the preview origin
```
Use the `testing_agent` for full regression after any feature/bugfix. Reports land in
`/app/test_reports/iteration_N.json` — fix ALL findings, even low priority.

— End of handoff. Good luck, successor. The user is technical, cost-conscious (asked to pause at
credit milestones), and wants a reliable home-lab monitor. Be honest about the Webmin-metrics and
self-hosted-push limitations; don't over-promise.
