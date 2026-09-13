# Self-hosting WebminPulse at home (Raspberry Pi 5)

This runs the **backend + MongoDB** on your own hardware so it can reach Webmin servers on
your LAN directly (private `192.168.x / 10.x` addresses that a cloud host can't see), and lets
you reach it from anywhere.

---

## 1. Hardware / OS
- Raspberry Pi 5 (4 GB fine, 8 GB nicer) — **or any 64-bit Linux box**.
- **64-bit OS** (Raspberry Pi OS 64-bit / Ubuntu). Required for MongoDB.
- Store data on an **NVMe (M.2 HAT) or USB SSD**, not the microSD (DB write wear + corruption).
- Keep it always-on; use the official 27 W PSU for Pi 5 + NVMe.

## 2. Install Docker
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # log out/in after this
```

## 3. Get the code + configure
Push this project to GitHub (Emergent → "Save to GitHub"), then on the Pi:
```bash
git clone <your-repo-url> webminpulse
cd webminpulse/selfhost
cp .env.example .env
# fill in secrets:
openssl rand -hex 32                                              # -> JWT_SECRET
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # -> SERVER_ENC_KEY
nano .env
```
> On a Pi **3/4** (older chips) change `mongo:7` to `mongo:4.4` in `docker-compose.yml`.
> The Pi **5** runs `mongo:7` fine.

## 4. Start it
```bash
docker compose up -d --build
docker compose logs -f backend        # should show "WebminPulse backend started"
curl http://localhost:8001/api/        # -> {"service":"WebminPulse API","status":"ok"}
```
The API is now on `http://<pi-lan-ip>:8001`.

## 5. Point the mobile app at your Pi
In the app's `frontend/.env`:
```
EXPO_PUBLIC_BACKEND_URL=http://<pi-lan-ip>:8001
```
- On the **same WiFi**, that's all you need.
- To use it **away from home**, expose the backend with a tunnel (next step) and set
  `EXPO_PUBLIC_BACKEND_URL` to the tunnel's HTTPS URL, then rebuild the app.

## 6. Remote access (away from home) — Cloudflare Tunnel (recommended)
No router ports opened; gives you a real HTTPS URL.
```bash
# install cloudflared, then:
cloudflared tunnel login
cloudflared tunnel create webminpulse
# route a hostname to the backend:
cloudflared tunnel route dns webminpulse api.yourdomain.com
cloudflared tunnel run --url http://localhost:8001 webminpulse
```
Then set `EXPO_PUBLIC_BACKEND_URL=https://api.yourdomain.com`.
(Alternatives: Tailscale, ngrok, or a router port-forward + DuckDNS — less preferred.)

You can also expose each **Webmin** server the same way so the app's "Open Webmin Panel" works
remotely, or just run the Pi backend on the LAN and reach *it* via the tunnel while it polls the
LAN Webmin boxes locally.

## 7. Check modes (new)
When adding a server you can choose how it's checked:
- **WEBMIN** – full HTTP(S) login: online + CPU/RAM + updates (+ "auth failed" detection).
- **TCP PORT** – just verifies the port is open (fast, works even before Webmin is set up).
- **PING** – ICMP "is the host alive". Needs `NET_RAW` (already set in compose) and ICMP allowed
  on your network. (In cloud sandboxes ICMP is usually blocked; on your LAN it works.)

## 8. Push notifications — important
Push delivery to your phone (offline / CPU / RAM / updates) works **regardless of your home
network** as long as the backend has outbound internet — the alert goes phone←push-provider←backend.

BUT the current build uses **Emergent-managed push**, whose key + device build are provisioned by
Emergent's deploy/build pipeline. On a fully self-hosted backend you must either:
  (a) keep using an Emergent-generated app build + push key, or
  (b) switch to a self-managed push path (e.g. Expo push tokens + Expo's push API / FCM+APNs).
See the note from support in the chat for the exact recommended path for your setup.
Leave `EMERGENT_PUSH_KEY=placeholder` until you've confirmed the approach.

## 9. Updating later
```bash
git pull
docker compose up -d --build
```

## Backups
Your data lives in the `mongo_data` Docker volume. Back it up:
```bash
docker exec wp-mongo sh -c 'mongodump --archive' > backup-$(date +%F).archive
```

---

# Game servers + Discord control

Start and stop dedicated game servers from a Discord channel. Servers stop
themselves after **12 hours** unless somebody extends them.

## Which of my games can do this?

See `backend/steam/README.md` — scan your library first, then configure the games
you actually want to host.

## Where the servers run

SteamCMD and essentially every dedicated server are **x86_64-only**, so the hosting
half cannot run on a Raspberry Pi. The scan, catalog, API and Discord bot all run
fine on ARM — only launching servers needs x86. Two supported layouts:

**A. Everything on the gameserver.** Run this whole stack on the x86_64 box and
leave `GAMESERVER_SSH_HOST` blank. Servers launch as local processes. Simplest.

**B. Backend on the Pi, servers on the gameserver.** Keep the backend where it
already watches your LAN, and point it at the gameserver over SSH:

```bash
GAMESERVER_SSH_HOST=gameserver.lan
GAMESERVER_SSH_USER=steam
GAMESERVER_SSH_KEY=/keys/id_ed25519
GAMESERVER_BASE_DIR=/opt/gameservers   # path on the GAMESERVER, not the Pi
```

Install/start/stop then run over SSH on that box. Set it up with a key, not a
password — the backend uses `BatchMode=yes` and will never sit on a prompt:

```bash
ssh-keygen -t ed25519 -f ./gameserver_key -N ""
ssh-copy-id -i ./gameserver_key.pub steam@gameserver.lan
```

Mount the private key into the container and point `GAMESERVER_SSH_KEY` at it.
Servers are started with `setsid`, so they keep running if the backend restarts
or the SSH connection drops.

## Requirements

- SteamCMD installed on whichever box runs the servers (on `PATH`, or set `STEAMCMD_PATH`).

```bash
sudo apt install software-properties-common
sudo add-apt-repository multiverse && sudo dpkg --add-architecture i386 && sudo apt update
sudo apt install steamcmd
```

## Creating the Discord bot

1. <https://discord.com/developers/applications> → **New Application** → **Bot** → copy the token.
2. Invite it with the `bot` and `applications.commands` scopes.
3. Put the token in `.env` as `DISCORD_BOT_TOKEN`, set `DISCORD_GUILD_ID` to your
   server's ID so slash commands register immediately, and set `DISCORD_OWNER_EMAIL`
   to the WebminPulse account whose servers the bot should control.
4. `docker compose up -d --build` → the log shows `Discord bot enabled`.

Leaving `DISCORD_BOT_TOKEN` blank disables the bot; everything else still runs.

## Commands

| Command | What it does |
|---|---|
| `/servers` | Every configured server, its status, and time left before auto-stop |
| `/start <server>` | Start a server. Sets the 12-hour clock. |
| `/stop <server>` | Stop it now |
| `/extend <server> [hours]` | Push auto-stop out, measured **from now** (default 6h, max 24h) |
| `/keepalive <server> [on]` | Exempt from auto-stop entirely; `off` re-arms the 12h timer |
| `/install <server>` | Download/update the server via SteamCMD |

Server names autocomplete. Set `DISCORD_ALLOWED_ROLE` to restrict start/stop/install
to one role — `/extend` stays open so players can keep their own session alive.

## The 12-hour rule

- Starting a server sets `auto_stop_at` to 12 hours out.
- A reaper runs every 60s. `GAMESERVER_WARN_BEFORE_MIN` (default 15) minutes before
  the deadline it posts a warning naming the extend command; at the deadline it stops
  the server and says so.
- `/extend 3` means *three hours from now*, not three hours added to whatever was
  left — so it behaves the way people expect when a session is nearly up.
- Stops are graceful: SIGTERM to the process group, then SIGKILL after
  `GAMESERVER_STOP_GRACE` seconds, so worlds get a chance to save.
- Every start/stop/extend is written to `gameserver_events` with who ran it.

Change the window with `GAMESERVER_AUTO_STOP_HOURS`; the whole system reads that
one value.

## If the backend restarts

Running servers are tracked by PID plus process start time, so a restarted backend
re-attaches to servers that are still up and marks crashed ones stopped instead of
showing a phantom "running". PID reuse is detected rather than trusted.
