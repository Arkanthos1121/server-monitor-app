"""Discord control surface for self-hosted game servers.

Optional: the backend runs fine without it. Set DISCORD_BOT_TOKEN to enable.
Every command routes through gameserver_service, so the 12-hour auto-stop rule
is identical whether a server was started from Discord or from the app.

Env:
  DISCORD_BOT_TOKEN        bot token (enables the bot)
  DISCORD_GUILD_ID         guild to sync commands to (instant instead of ~1h)
  DISCORD_OWNER_EMAIL      WebminPulse account whose servers the bot controls
  DISCORD_CHANNEL_ID       channel for auto-stop warnings and notices
  DISCORD_ALLOWED_ROLE     role name required to start/stop (optional)
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import gameservers as gs
import gameserver_service as svc

logger = logging.getLogger("webminpulse.discord")

TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
GUILD_ID = os.environ.get("DISCORD_GUILD_ID", "").strip()
OWNER_EMAIL = os.environ.get("DISCORD_OWNER_EMAIL", "").strip().lower()
CHANNEL_ID = os.environ.get("DISCORD_CHANNEL_ID", "").strip()
ALLOWED_ROLE = os.environ.get("DISCORD_ALLOWED_ROLE", "").strip()

_bot = None
_db = None
_owner_id: Optional[str] = None

STATUS_ICON = {"running": "🟢", "starting": "🟡", "stopping": "🟠",
               "installing": "🔵", "stopped": "⚪"}


def enabled() -> bool:
    return bool(TOKEN)


async def _owner_user_id() -> Optional[str]:
    """The account whose servers the bot manages."""
    global _owner_id
    if _owner_id:
        return _owner_id
    q = {"email": OWNER_EMAIL} if OWNER_EMAIL else {}
    user = await _db.users.find_one(q, {"_id": 0}, sort=[("created_at", 1)])
    if not user:
        logger.warning("discord: no WebminPulse user found (set DISCORD_OWNER_EMAIL)")
        return None
    _owner_id = user["user_id"]
    return _owner_id


def _permitted(interaction) -> bool:
    if not ALLOWED_ROLE:
        return True
    roles = getattr(getattr(interaction, "user", None), "roles", []) or []
    return any(getattr(r, "name", "") == ALLOWED_ROLE for r in roles)


async def _resolve(interaction, name: str):
    """Return (record, error_message)."""
    uid = await _owner_user_id()
    if not uid:
        return None, "No WebminPulse account is linked to this bot."
    rec = await svc.find(uid, name)
    if not rec:
        rows = await svc.list_for_user(uid)
        known = ", ".join(f"`{r['name']}`" for r in rows[:12]) or "none configured"
        return None, f"No server matches `{name}`. Known servers: {known}"
    return rec, None


def build(db):
    """Construct the bot. Returns None when discord.py or the token is absent."""
    global _bot, _db
    _db = db
    if not enabled():
        return None
    try:
        import discord
        from discord import app_commands
    except ImportError:
        logger.warning("discord: DISCORD_BOT_TOKEN set but discord.py is not installed")
        return None

    intents = discord.Intents.default()
    bot = discord.Client(intents=intents)
    tree = app_commands.CommandTree(bot)

    async def server_names(interaction, current: str):
        uid = await _owner_user_id()
        rows = await svc.list_for_user(uid) if uid else []
        cur = (current or "").lower()
        return [app_commands.Choice(name=f"{r['name']} ({r.get('game_name') or '?'})"[:100],
                                    value=r["name"])
                for r in rows if cur in r["name"].lower()][:25]

    # ------------------------------------------------------------ commands --
    @tree.command(name="servers", description="List every configured game server and its status")
    async def servers_cmd(interaction):
        await interaction.response.defer(thinking=True)
        uid = await _owner_user_id()
        rows = [await svc.reconcile(r) for r in (await svc.list_for_user(uid) if uid else [])]
        if not rows:
            await interaction.followup.send(
                "No game servers configured yet. Add one from the WebminPulse app, "
                "or scan your Steam library to see what you can host.")
            return
        lines = []
        for r in rows:
            icon = STATUS_ICON.get(r.get("status"), "⚪")
            bits = [f"{icon} **{r['name']}** — {r.get('game_name') or 'unknown game'}"]
            if r.get("status") == "running":
                rem = gs.fmt_remaining(gs.remaining_seconds(r))
                bits.append(f"port {r.get('port')} · auto-stop in {rem}")
            elif not r.get("installed"):
                bits.append("not installed")
            lines.append("\n".join(["  ".join(bits[:1]), f"   ↳ {bits[1]}" if len(bits) > 1 else ""]).rstrip())
        await interaction.followup.send("\n".join(lines)[:1900])

    @tree.command(name="start", description="Start a game server (auto-stops after 12h)")
    @app_commands.describe(server="Which server to start")
    @app_commands.autocomplete(server=server_names)
    async def start_cmd(interaction, server: str):
        if not _permitted(interaction):
            await interaction.response.send_message(
                f"You need the **{ALLOWED_ROLE}** role to do that.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        rec, err = await _resolve(interaction, server)
        if err:
            await interaction.followup.send(err)
            return
        ok, msg = await svc.start(rec, actor=f"discord:{interaction.user}")
        await interaction.followup.send(msg)

    @tree.command(name="stop", description="Stop a running game server")
    @app_commands.describe(server="Which server to stop")
    @app_commands.autocomplete(server=server_names)
    async def stop_cmd(interaction, server: str):
        if not _permitted(interaction):
            await interaction.response.send_message(
                f"You need the **{ALLOWED_ROLE}** role to do that.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        rec, err = await _resolve(interaction, server)
        if err:
            await interaction.followup.send(err)
            return
        ok, msg = await svc.stop(rec, actor=f"discord:{interaction.user}", reason="stopped from Discord")
        await interaction.followup.send(msg)

    @tree.command(name="extend", description="Keep a server up longer than its 12h limit")
    @app_commands.describe(server="Which server", hours="Extra hours from now (default 6)")
    @app_commands.autocomplete(server=server_names)
    async def extend_cmd(interaction, server: str, hours: Optional[float] = 6.0):
        await interaction.response.defer(thinking=True)
        rec, err = await _resolve(interaction, server)
        if err:
            await interaction.followup.send(err)
            return
        ok, msg = await svc.extend(rec, hours, actor=f"discord:{interaction.user}")
        await interaction.followup.send(msg)

    @tree.command(name="keepalive", description="Exempt a server from the 12h auto-stop entirely")
    @app_commands.describe(server="Which server", on="True to pin it up, False to re-arm the timer")
    @app_commands.autocomplete(server=server_names)
    async def keepalive_cmd(interaction, server: str, on: bool = True):
        if not _permitted(interaction):
            await interaction.response.send_message(
                f"You need the **{ALLOWED_ROLE}** role to do that.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        rec, err = await _resolve(interaction, server)
        if err:
            await interaction.followup.send(err)
            return
        ok, msg = await svc.set_keepalive(rec, on, actor=f"discord:{interaction.user}")
        await interaction.followup.send(msg)

    @tree.command(name="install", description="Download/update a server with SteamCMD")
    @app_commands.describe(server="Which server to install")
    @app_commands.autocomplete(server=server_names)
    async def install_cmd(interaction, server: str):
        if not _permitted(interaction):
            await interaction.response.send_message(
                f"You need the **{ALLOWED_ROLE}** role to do that.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        rec, err = await _resolve(interaction, server)
        if err:
            await interaction.followup.send(err)
            return
        await interaction.followup.send(f"Installing **{rec['name']}** — this can take a while…")
        ok, msg = await svc.install(rec, actor=f"discord:{interaction.user}")
        await interaction.followup.send(msg)

    @tree.command(name="disk", description="Free space on the gameserver, and any unused drives")
    async def disk_cmd(interaction):
        await interaction.response.defer(thinking=True)
        rep = await gs.disk_report()
        if rep.get("error"):
            await interaction.followup.send(f"Could not read disks on {rep['host']}: {rep['error']}")
            return
        lines = [f"**Disks on {rep['host']}**"]
        for f in sorted(rep["filesystems"], key=lambda x: -x["avail_bytes"]):
            lines.append(f"  `{f['mount']}` — {gs.human_bytes(f['avail_bytes'])} free "
                         f"of {gs.human_bytes(f['size_bytes'])} ({f['use_pct']} used)")
        spare = rep.get("unused_disks") or []
        if spare:
            lines.append("")
            lines.append("**Unused drives** (no filesystem — format before use):")
            for d in spare:
                model = f" · {d['model']}" if d["model"] else ""
                lines.append(f"  `/dev/{d['name']}` — {gs.human_bytes(d['size_bytes'])}{model}")
        lines.append("")
        lines.append(f"Servers install to `{rep['install_root']}`.")
        await interaction.followup.send("\n".join(lines)[:1900])

    @bot.event
    async def on_ready():
        try:
            if GUILD_ID:
                guild = discord.Object(id=int(GUILD_ID))
                tree.copy_global_to(guild=guild)
                await tree.sync(guild=guild)
            else:
                await tree.sync()
            logger.info(f"discord: logged in as {bot.user}, commands synced")
        except Exception as e:
            logger.warning(f"discord: command sync failed: {e}")

    _bot = bot
    return bot


async def announce(text: str):
    """Post an unprompted notice (auto-stop warnings, reaper actions)."""
    if not (_bot and CHANNEL_ID):
        return
    try:
        ch = _bot.get_channel(int(CHANNEL_ID))
        if ch is None:
            ch = await _bot.fetch_channel(int(CHANNEL_ID))
        await ch.send(text)
    except Exception as e:
        logger.warning(f"discord: announce failed: {e}")


async def run(db):
    bot = build(db)
    if not bot:
        return
    try:
        await bot.start(TOKEN)
    except Exception as e:
        logger.warning(f"discord: bot stopped: {e}")
