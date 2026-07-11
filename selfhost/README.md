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
