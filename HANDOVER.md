# Handover — Game Server Installs + Discord Control Bot

**Status:** code complete and pushed, 241 tests passing. Nothing has been
installed or run on real hardware yet. This document takes it from there.

**Branch:** `claude/steam-dedicated-server-scan-m0g73g`
**Repo:** `https://github.com/Arkanthos1121/server-monitor-app`

---

## 0. Read this first

Everything below runs **on the gameserver itself**, not from a cloud session.
If you are an agent reading this: you need real shell access to that machine —
`lsblk`, `sudo`, `steamcmd`, systemd. If you cannot run those, stop and say so
rather than producing commands for someone to paste.

**Show every destructive command before running it.** Phase 1 deletes
partitions; a wrong device name there destroys data that is not backed up.

---

## 1. What was built

A control plane for self-hosted Steam game servers, driven from Discord.

| Piece | File | What it does |
|---|---|---|
| Library scan | `backend/steam/scanner.py` | Finds which Steam games can run a dedicated server |
| Verified catalog | `backend/steam/catalog.json` | 78 game→server pairs, each checked against live Steam data |
| Launch profiles | `backend/steam/profiles.py` | Per-game binary, args, ports, RCON save command, runner |
| Lifecycle | `backend/gameservers.py` | SteamCMD install, spawn, save-then-stop, disk reporting |
| Service layer | `backend/gameserver_service.py` | Shared by REST API and Discord so both obey the same rules |
| Stop permissions | `backend/stop_policy.py` | Who may stop what, and when |
| Player counts | `backend/a2s.py` | Steam A2S queries — drives idle shutdown and the stop guard |
| RCON | `backend/rcon.py` | Saves worlds before shutdown |
| Discord bot | `backend/discord_bot.py` | Slash commands, optional — off unless a token is set |

Run the tests any time to confirm nothing is broken:

```bash
cd backend && python3 -m pytest tests/ -q --ignore=tests/test_webminpulse.py
# expect: 241 passed
```

(`tests/test_webminpulse.py` is pre-existing and fails on a hardcoded
`/app/frontend/.env` path. Not ours, not a regression.)

---

## 2. The target machine — storage is DONE

Verified on the gameserver, 2026-10-09:

```
nvme0n1   476.9G  AirDisk 512GB SSD
  p1        100M  vfat  SYSTEM        /boot/efi         ← NEVER DELETE
  p2      230.9G  ext4  gameservers   /opt/gameservers   ← reclaimed from Windows
  p4      244.1G  ext4                /
nvme1n1   953.9G  Predator SSD GM7000 1TB
  p1        512M  vfat  bootfs                           ← DO NOT TOUCH
  p2      953.4G  ext4  rootfs                           ← Raspberry Pi OS install
sda/sdb/sdc  3 x 7.3T  → /mnt/plex-disk{1,2,3}
  pooled by mergerfs (FUSE) as 22T at /mnt/plex-media
```

**Phase 1 is complete.** Windows C: and its Recovery partition were deleted and
the space became `nvme0n1p2` — 230.9 GB of ext4, labelled `gameservers`, mounted
at `/opt/gameservers`. The EFI partition was correctly kept. Skip §3 entirely;
it is retained only as a record of what was done.

That is comfortably more than the ~155 GB needed.

**Do not relocate game servers to `/mnt/plex-media`.** It has 8.7 TB free and
looks tempting, but it is a **mergerfs FUSE union** across three disks. SteamCMD
and running servers do heavy small-file I/O and rely on file locking, both of
which behave badly on a FUSE union — expect corrupted installs and servers that
hang on save. The NVMe partition is the right home.

**Standing rule:** `nvme1n1` carries a `bootfs`/`rootfs` pair, the standard
Raspberry Pi OS layout. It is not spare capacity. Do not format it.

---

## 3. Phase 1 — Reclaim the Windows partition  ✅ ALREADY DONE

**Completed 2026-10-09. Kept as a record; do not re-run any of it.**

### 3.1 Identify p3 before touching anything

```bash
sudo blkid -p /dev/nvme0n1p3
sudo file -s /dev/nvme0n1p3
```

- Reports `ntfs` → it is Windows, continue.
- Reports `BitLocker` → **stop.** Encrypted; must be handled from Windows first.
- Reports nothing → stop and investigate. Do not delete an unidentified partition.

### 3.2 Save the Windows product key

On OEM machines the key lives in UEFI firmware, not on disk, so it survives:

```bash
sudo strings /sys/firmware/acpi/tables/MSDM | tail -1
```

No MSDM file means a digital licence tied to the Microsoft account — nothing to
save; it reactivates on reinstall. Store the key somewhere **not on this disk**.

### 3.3 Delete and recreate

```bash
sudo parted /dev/nvme0n1 print          # confirm numbering first

sudo parted /dev/nvme0n1 rm 3           # Windows C:
sudo parted /dev/nvme0n1 rm 2           # Microsoft Reserved
sudo parted /dev/nvme0n1 rm 5           # Recovery
# p1 (EFI) and p4 (/) stay

sudo parted /dev/nvme0n1 print free     # note Start and End of the free gap
```

**Do not try to grow `/` into the gap.** p3 sits *before* p4, so extending p4
means physically relocating 244 GB of root filesystem — hours on a live USB,
and a power cut leaves the machine unbootable. Create a new partition instead:

```bash
sudo parted -a optimal /dev/nvme0n1 mkpart gameservers ext4 <START> <END>
sudo partprobe /dev/nvme0n1
lsblk /dev/nvme0n1                      # confirm the new partition's name
```

### 3.4 Format and mount

```bash
PART=/dev/nvme0n1p3                     # whatever lsblk just showed

sudo mkfs.ext4 -L gameservers -m 0 "$PART"     # -m 0: no root reserve, ~11 GB back
sudo mkdir -p /opt/gameservers
sudo cp /etc/fstab /etc/fstab.bak

UUID=$(sudo blkid -s UUID -o value "$PART")
echo "UUID=$UUID /opt/gameservers ext4 defaults,noatime 0 2" | sudo tee -a /etc/fstab

sudo mount -a && df -h /opt/gameservers
sudo update-grub                        # drop the dead Windows boot entry
```

Mount by UUID, never `/dev/sdX` — device letters shuffle when disks are added,
and a wrong fstab entry fails the boot.

---

## 4. Phase 2 — SteamCMD and the server installs

### 4.1 Install SteamCMD

```bash
sudo add-apt-repository multiverse
sudo dpkg --add-architecture i386
sudo apt update
sudo apt install -y steamcmd

sudo useradd -m steam 2>/dev/null || true
sudo chown -R steam:steam /opt/gameservers
```

### 4.2 Smoke test first — Valheim

2 GB, native Linux, no login required. Prove the chain before committing to a
21 GB download.

```bash
sudo -u steam steamcmd \
  +force_install_dir /opt/gameservers/896660 \
  +login anonymous +app_update 896660 validate +quit

ls /opt/gameservers/896660/valheim_server.x86_64   # must exist
```

If that works, everything else is the same shape.

### 4.3 The 21 native Linux servers — 129 GB total

```bash
for app in 376030 294420 403240 2089300 222860 237410 222840 4020 258550 \
           233780 2394010 343050 223350 2465200 215350 896660 1829350 \
           1110390 1948160 3792580 556450; do
  echo "=== $app ==="
  sudo -u steam steamcmd +force_install_dir /opt/gameservers/$app \
       +login anonymous +app_update $app validate +quit
done
```

| App ID | Game | Size | Default port |
|---|---|---|---|
| 376030 | ARK: Survival Evolved | 21.4 GB | 7777 |
| 294420 | 7 Days to Die | 16.4 GB | 26900 |
| 403240 | Squad | 13.3 GB | |
| 2089300 | Icarus | 9.7 GB | 17777 |
| 222860 | Left 4 Dead 2 | 9.1 GB | 27015 |
| 237410 | Insurgency | 8.8 GB | |
| 222840 | Left 4 Dead | 8.2 GB | |
| 4020 | Garry's Mod | 6.4 GB | 27015 |
| 258550 | Rust | 5.5 GB | 28015 |
| 233780 | Arma 3 | 5.0 GB | ⚠ needs login |
| 2394010 | Palworld | 4.6 GB | 8211 |
| 343050 | Don't Starve Together | 4.2 GB | |
| 223350 | DayZ | 3.7 GB | ⚠ needs login |
| 2465200 | Sons Of The Forest | 3.3 GB | |
| 215350 | Killing Floor | 2.2 GB | |
| 896660 | Valheim | 2.0 GB | 2456 |
| 1829350 | V Rising | 1.9 GB | 9876 |
| 1110390 | Unturned | 1.8 GB | 27015 |
| 1948160 | Euro Truck Simulator 2 | 1.2 GB | |
| 3792580 | SCUM | 0.1 GB | |
| 556450 | The Forest | 0.1 GB | |

⚠ **Arma 3 (233780) and DayZ (223350) reject anonymous login.** Use
`+login <your_steam_account>` for those two and complete the Steam Guard prompt
once; the session is then cached for that user.

### 4.4 Bundled servers — Factorio and Terraria

These ship the server inside the game rather than as a separate Steam app, so
they are not in the loop above.

- **Factorio** (2.2 GB) — download the headless build from factorio.com, not Steam.
- **Terraria** (0.8 GB) — `TerrariaServer.bin.x86_64` lives in the game install.

Both need `launch_cmd` set explicitly on their server record (see §7.2).

---

## 5. Phase 3 — ARK: Survival Ascended and Space Engineers

Both are Windows-only servers. There is no Linux build — the "linux" depots
Steam lists for them are 0.1 GB of redistributables, not a server.

They run through a compatibility layer. SteamCMD must be told to fetch the
Windows depots, and **the flag has to come before `+login`**:

```bash
# ARK: Survival Ascended — 11.4 GB
sudo -u steam steamcmd +@sSteamCmdForcePlatformType windows \
  +force_install_dir /opt/gameservers/2430930 \
  +login anonymous +app_update 2430930 validate +quit

# Space Engineers — 7.9 GB
sudo -u steam steamcmd +@sSteamCmdForcePlatformType windows \
  +force_install_dir /opt/gameservers/298740 \
  +login anonymous +app_update 298740 validate +quit
```

`backend/steam/profiles.py` already marks 2430930 as `runner: proton` and
298740 as `runner: wine`, so `/install` and `/start` handle the flag and the
launch wrapper automatically once these paths are set:

```bash
PROTON_PATH=/opt/proton/proton                  # GE-Proton is the usual choice
WINE_PATH=wine
STEAM_COMPAT_CLIENT_INSTALL_PATH=/opt/steam
```

Space Engineers additionally needs `winetricks dotnet48` in its prefix
(`/opt/gameservers/<dir>/wineprefix`).

**Expect to adjust `PROTON_PATH` on first run** — these paths were never
verified against a real install.

**RAM is the real constraint, not disk.** ARK: Survival Ascended wants 12–16 GB
for a single map, plus Proton overhead. On a 16 GB box it runs alone. Check
`free -h` before planning concurrency.

---

## 6. Phase 4 — Backend and database

The backend polls servers, runs the idle reaper, and serves the API the Discord
bot and mobile app use.

```bash
cd /opt
sudo git clone https://github.com/Arkanthos1121/server-monitor-app
cd server-monitor-app
sudo git checkout claude/steam-dedicated-server-scan-m0g73g
```

### Docker (simplest)

```bash
cd selfhost
cp .env.example .env
openssl rand -hex 32                                                        # → JWT_SECRET
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # → SERVER_ENC_KEY
nano .env
docker compose up -d --build
docker compose logs -f backend      # expect "WebminPulse backend started"
curl http://localhost:8001/api/     # → {"service":"WebminPulse API","status":"ok"}
```

### Running servers on a *different* box than the backend

If the backend lives on the Pi and the servers on this machine, set:

```bash
GAMESERVER_SSH_HOST=gameserver.lan
GAMESERVER_SSH_USER=steam
GAMESERVER_SSH_KEY=/keys/id_ed25519
GAMESERVER_BASE_DIR=/opt/gameservers     # path on the GAMESERVER
```

Install, start, stop and liveness then run over SSH. Use a key, not a password —
the backend uses `BatchMode=yes` and will never sit on a prompt. Servers launch
under `setsid`, so they survive a backend restart or a dropped connection.

Leave those blank to run everything on one box.

---

## 7. Phase 5 — Discord bot

### 7.1 Create and connect it

1. <https://discord.com/developers/applications> → **New Application** → **Bot** → copy the token
2. Invite it with the `bot` and `applications.commands` scopes
3. Fill in `.env`:

```bash
DISCORD_BOT_TOKEN=          # enables the bot; blank disables it entirely
DISCORD_GUILD_ID=           # your server's ID → slash commands register instantly
DISCORD_OWNER_EMAIL=        # the WebminPulse account the bot acts as
DISCORD_CHANNEL_ID=         # where auto-stop warnings are posted
DISCORD_ADMIN_ROLE=         # e.g. "Server Admin"; blank → Manage Server counts as admin
```

4. `docker compose up -d --build` → log shows `Discord bot enabled`

### 7.2 Register the servers

Each server needs a record before Discord can control it. Via the API:

```bash
TOKEN=<your JWT from /api/auth/login>

curl -X POST http://localhost:8001/api/gameservers \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"valheim-main","game_appid":892970,"game_name":"Valheim",
       "server_appid":896660,"port":2456,"server_password":"changeme"}'
```

**All 23 servers have launch profiles** (32 games covered in total), so none
needs `launch_cmd` set by hand. Factorio and Terraria are the exceptions —
they're bundled, see §4.4.

**Nine of them also get a starter config written on first install**, rendered
from `backend/gameconfigs/<appid>/` with the server's name, port, player count
and passwords filled in:

| Game | Config written |
|---|---|
| Arma 3 | `server.cfg` |
| DayZ | `serverDZ.cfg` |
| Don't Starve Together | `cluster/cluster.ini`, `cluster/Master/server.ini` |
| Euro Truck Simulator 2 | `server_config.sii` |
| Insurgency | `insurgency/cfg/server.cfg` |
| Left 4 Dead | `left4dead/cfg/server.cfg` |
| Sons Of The Forest | `userdata/dedicatedserver.cfg` |
| Squad | `SquadGame/ServerConfig/Server.cfg`, `Admins.cfg` |
| The Forest | `config.cfg` |

An existing config is **never overwritten** — reinstalling won't undo your
tuning. Killing Floor and SCUM are deliberately excluded: both ship or generate
their own configs, and replacing those loses defaults the game expects.

### ⚠ Verify the binary paths after installing

Profile binary paths for the eleven added on 2026-10-09 come from each game's
**documentation, not a verified install**. Vendors move binaries. Run this once
the installs finish:

```bash
cd /opt/server-monitor-app/backend
python3 -m steam.verify_profiles
```

It checks each installed directory for the binary its profile declares and, when
one is missing, lists the plausible executables it did find so you can correct
`linux`/`windows` in `steam/profiles.py`. Exit code 1 means something needs
fixing. Do this **before** wiring up Discord — a wrong path surfaces as
*"Server binary missing"* and nothing more useful.

### 7.3 Commands

| Command | Effect |
|---|---|
| `/servers` | Every server, status, who's on it, who started it |
| `/players` | Live player counts |
| `/start <server>` | Start it. Records you as the starter. |
| `/stop <server>` | Stop it — subject to the rules in §8.2 |
| `/stop <server> force:True` | Admin override; announced publicly, audited |
| `/requeststop <server>` | Ask players to wrap up; stops in 5 min unless cancelled |
| `/keepplaying <server>` | Cancel a pending stop. Open to anyone. |
| `/extend <server> [hours]` | Keep an empty server up anyway (default 6h, max 24h) |
| `/keepalive <server> [on]` | Exempt from idle shutdown entirely |
| `/install <server>` | SteamCMD install/update |
| `/disk` | Free space, and any unformatted drives |

---

## 8. How it behaves

### 8.1 The 12-hour idle rule

The clock measures **idle time, not uptime**. A server with people on it is
never shut down, however long it has been running.

- Hourly (`GAMESERVER_PLAYER_POLL_SECONDS`) each running server is asked its
  player count over Steam A2S.
- Someone online → clock resets. Last player leaves → clock starts.
- 12 hours empty → world saved, server stopped.
- 15 minutes before that, a warning is posted. **Joining the server cancels the
  shutdown — no command needed.**
- `/extend 3` keeps an empty server up 3 more hours, measured from now.

Two cadences on purpose: network polls are hourly, but the countdown is
arithmetic on a timestamp and ticks every minute, so shutdown lands on time
rather than up to an hour late. Stop decisions always re-query live.

A server that cannot be queried (Palworld and Satisfactory use REST, not A2S)
falls back to uptime — it still stops eventually. **An unknown player count is
never treated as empty.**

### 8.2 Who may stop a server

| Who | Empty | People playing |
|---|---|---|
| Whoever ran `/start` | ✅ | ❌ |
| Anyone else | ❌ | ❌ |
| Admin | ✅ | ✅ with `force:True` |
| Automation | ✅ | never applies |

The starter cannot stop their own server while others are playing on it — that
is the griefing case this exists to prevent. Admins must pass `force:True`
explicitly, and it posts publicly plus writes a `force_stop` audit row.

`GAMESERVER_EMPTY_STOP_POLICY=anyone` relaxes only the empty-server rule.

### 8.3 Saving before shutdown

Every stop saves first — manual, requested, or automatic:

1. Where the game speaks Source RCON (ARK SE/SA, 7 Days to Die, Palworld), an
   explicit save command is sent and acknowledged.
2. Then SIGTERM to the process group, with a 120 s grace
   (`GAMESERVER_SAVE_STOP_GRACE`) so a large world finishes flushing. Killing
   mid-write is how saves corrupt.
3. SIGKILL only if it overstays.

Rust uses WebSocket RCON and Space Engineers has no standard console, so those
rely on the engine's own save-on-exit. RCON save needs a password on the record.

---

## 9. Verification checklist

- [x] `/opt/gameservers` exists — 230.9 GB ext4 on nvme0n1p2
- [ ] `df -h /opt/gameservers` confirms free space and `steam` owns it
- [ ] Valheim installs and `valheim_server.x86_64` exists
- [ ] Backend logs `WebminPulse backend started`
- [ ] `curl localhost:8001/api/` returns ok
- [ ] Bot logs `Discord bot enabled`; `/servers` responds in Discord
- [ ] `/start valheim-main` → process appears in `ps aux | grep valheim`
- [ ] `/players` shows 0, then 1 after you connect from the game client
- [ ] `/stop valheim-main` as a non-starter → refused
- [ ] `/stop valheim-main` as the starter → stops, world saved
- [ ] `python3 -m steam.verify_profiles` exits 0
- [ ] `backend/tests` still 241 passing

---

## 10. Known gaps

Be honest about these rather than discovering them at 2am.

- **Nothing has run on real hardware.** No SteamCMD install, no Discord guild,
  no Proton launch. The logic is tested; the integration is not.
- **Proton/Wine paths are guesses.** `PROTON_PATH=/opt/proton/proton` will
  almost certainly need changing.
- **A2S query ports are per-game assumptions** (game port +1 by default, +0 for
  Source engine). Override with `query_port` in `profiles.py` if `/players`
  reports nothing for a server you know has people on it.
- **Binary paths for 11 profiles are unverified** — written from game docs, not
  a real install. `python3 -m steam.verify_profiles` checks them against what
  SteamCMD actually laid down; expect to correct one or two.
- **Starter configs are minimal.** They produce a joinable server, not a tuned
  one. Arma 3 and DayZ in particular have far more settings worth reading up on.
- **`/keepplaying` is open to anyone in the channel** — deliberate, see
  `memory/PRD.md` § Decisions. Do not "fix" it.
- **Arma 3 and DayZ need a real Steam login** for SteamCMD.
- **The frontend Steam scan screen** (`frontend/app/steam.tsx`) typechecks but
  has never been run against a live backend.

---

## 11. Troubleshooting

| Symptom | Likely cause |
|---|---|
| `/start` → "No launch profile for this game" | Set `launch_cmd` on the record (§7.2) |
| `/start` → "Server exited immediately" | Check `<install_dir>/wp-server.log` |
| `/players` always blank for one server | Wrong query port — set `query_port` in `profiles.py` |
| Server never auto-stops | Player count unknown, or `keepalive` is on. Check `/servers` |
| Server stops with people on it | Should be impossible. Check `gameserver_events` and file a bug |
| `steamcmd` "Failed to install app" on ARK/DayZ | Needs a real Steam login, not anonymous |
| Proton launch fails instantly | `PROTON_PATH` wrong, or `compatdata` prefix not writable by `steam` |
| Bot online but no slash commands | `DISCORD_GUILD_ID` unset — global sync takes up to an hour |

Useful reads:

- `selfhost/README.md` — self-host setup in depth
- `backend/steam/README.md` — the library scan and how detection works
- `memory/PRD.md` — full history, decisions, and why things are the way they are
