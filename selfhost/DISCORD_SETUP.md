# Discord bot setup — step by step

Written for the case this most often lands in: **the bot shows online in your
member list, but typing `/` offers none of its commands.**

That symptom means the token is fine and `discord.py` is installed — the bot
logged in. What failed is *registering the slash commands*, and there are only
two realistic causes:

1. The invite didn't grant `applications.commands`, so the bot is allowed to sit
   in your server but not to register commands in it.
2. `DISCORD_GUILD_ID` points at the wrong place (a channel id, or a server the
   bot isn't in).

Since 2026-10-10 the bot no longer registers commands globally when
`DISCORD_GUILD_ID` is unset — it syncs directly to **every server it is in**,
which appears instantly. So leaving that variable blank is now a valid choice,
and a wrong value is worse than no value.

Work through this in order. Steps 1–3 take about five minutes.

---

## Step 0 — Run the diagnosis

```bash
cd /opt/server-monitor-app && git pull
cd selfhost && docker compose up -d --build
docker compose exec backend python3 diagnose_discord.py
```

It logs in with your real token and prints which servers the bot can see **with
their ids**, which commands Discord has registered where, and a verdict naming
the exact fix. Do what it says; the rest of this file is background.

If you'd rather read the log directly:

```bash
docker compose logs backend | grep -i discord
```

You're looking for one of these lines:

| Log line | Go to |
|---|---|
| `command sync refused (Missing Access)` | Step 1 (re-invite) |
| `DISCORD_GUILD_ID is not set … synced GLOBALLY` | Step 3 (guild ID) |
| `no WebminPulse account matches DISCORD_OWNER_EMAIL` | Step 5 |
| `logged in as … commands synced` and nothing else | Step 6 |

If you're unsure, just do Steps 1–4. They're harmless to repeat.

---

## Step 1 — Get your Application ID

1. Go to <https://discord.com/developers/applications>
2. Click your bot's application
3. On **General Information**, find **Application ID** and click **Copy**

It's an 18–19 digit number. This is *not* the bot token and not the Client
Secret — those are on the Bot and OAuth2 pages respectively.

---

## Step 2 — Re-invite the bot with the right scope

This is the usual culprit. The "Add Bot" flow in the developer portal grants
only the `bot` scope unless you explicitly ask for `applications.commands`, and
without that second scope the bot can join your server but never register a
single slash command.

**You do not need to kick the bot first.** Re-inviting over the top just adds
the missing scope.

Take this URL, replace `YOUR_APP_ID` with the Application ID from Step 1, and
open it in a browser:

```
https://discord.com/api/oauth2/authorize?client_id=YOUR_APP_ID&permissions=277025508352&scope=bot%20applications.commands
```

Then:

1. Pick your server from the dropdown
2. Click **Continue**
3. Leave the permissions as they are and click **Authorize**

The permission number grants: read/send messages, embed links, read history,
and use slash commands. Nothing destructive.

> Prefer to build it yourself? In the developer portal: **OAuth2 → URL
> Generator**, tick **bot** *and* **applications.commands** under Scopes, then
> tick the permissions you want. Both scope boxes matter — ticking only `bot`
> reproduces the exact problem you're debugging.

---

## Step 3 — Get your Server (Guild) ID

Without this, commands register globally and take up to an hour to appear. With
it, they appear instantly.

1. In Discord: **Settings (gear) → Advanced → Developer Mode → On**
2. Close settings
3. **Right-click your server's icon** in the far-left sidebar
4. Click **Copy Server ID**

⚠ It must be the **server** icon, not a channel. A channel ID here makes the bot
sync commands to a guild it isn't in — which looks exactly like doing nothing.

While you're here, also right-click the channel you want auto-stop warnings
posted in → **Copy Channel ID**. That's `DISCORD_CHANNEL_ID`.

---

## Step 4 — Fill in the config

```bash
cd /opt/server-monitor-app/selfhost
nano .env
```

Set these four:

```bash
DISCORD_BOT_TOKEN=          # Bot page → Reset Token → Copy. NOT the Client Secret.
DISCORD_GUILD_ID=           # server ID from Step 3
DISCORD_CHANNEL_ID=         # channel ID for auto-stop warnings
DISCORD_OWNER_EMAIL=        # the email you registered in the app with
```

`DISCORD_OWNER_EMAIL` decides whose game servers the bot manages. If it matches
no registered account, the bot comes online and every command refuses — see
Step 5.

Leave `DISCORD_ADMIN_ROLE` blank to start. Blank means anyone with **Manage
Server** in Discord counts as an admin, which is enough to get going.

---

## Step 5 — Restart and check

```bash
docker compose up -d --build
docker compose logs -f backend | grep -i discord
```

Success looks like:

```
discord: logged in as YourBot#1234, commands synced
```

with no `error` lines after it.

If you see `no WebminPulse account matches DISCORD_OWNER_EMAIL=...`, the bot is
running fine but pointed at an account that doesn't exist. Register that email
in the app (or correct the value), then restart.

---

## Step 6 — Check in Discord

1. **Fully quit and reopen Discord.** Not just the window — quit the app. On
   desktop, `Ctrl+R` forces a reload. The client caches the command list
   aggressively and this alone fixes a surprising number of cases.
2. In any channel the bot can see, type `/`
3. Your bot should appear in the picker with: `servers`, `players`, `start`,
   `stop`, `requeststop`, `keepplaying`, `extend`, `keepalive`, `install`, `disk`

Run `/servers` first. Expected on a fresh install:

> No game servers configured yet. Add one from the WebminPulse app, or scan your
> Steam library to see what you can host.

That response means **everything is working** — the bot reached the backend,
authenticated as your account, and queried the database. There just aren't any
servers registered yet.

---

## Still nothing?

Check these in order:

- **Is the bot actually in the right server?** It can be online in *a* server
  and absent from the one you're typing in.
- **Can it see the channel?** A channel with permissions that exclude the bot
  won't offer its commands. Try a channel everyone can access.
- **Did `docker compose up -d --build` actually restart it?** `docker compose ps`
  should show a recent uptime for `wp-backend`.
- **Is `DISCORD_GUILD_ID` the server, not a channel?** Easy to get backwards.

If all four check out, grab the full log and we'll look at it together:

```bash
docker compose logs backend --tail 200 > /tmp/backend.log
```

---

## What to do once commands appear

Register a server so `/servers` has something to show. Valheim is the easiest
first one — small, native Linux, already has a launch profile:

```bash
# get a token (use the account from DISCORD_OWNER_EMAIL)
TOKEN=$(curl -s -X POST http://localhost:8001/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"yourpassword"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')

curl -X POST http://localhost:8001/api/gameservers \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"valheim-main","game_appid":892970,"game_name":"Valheim",
       "server_appid":896660,"port":2456,"server_password":"pickone"}'
```

Then in Discord: `/servers` lists it, `/install valheim-main` updates it, and
`/start valheim-main` brings it up.

The real end-to-end test is `/players` showing **1** after you join from the
game client — that exercises the A2S query the whole idle-shutdown rule depends
on. If it shows 0 while you're standing in the world, the query port is wrong
for that game; say so and it's a one-line profile fix.
