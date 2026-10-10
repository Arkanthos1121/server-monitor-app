"""One-shot Discord diagnosis. Run it, read the verdict, do what it says.

    docker compose exec backend python3 diagnose_discord.py

Logs in with your real token, lists the guilds the bot can actually see, asks
Discord which commands are registered where, and checks the account the bot
acts as. It changes nothing except registering commands when you pass --fix.
"""
from __future__ import annotations

import asyncio
import os
import sys

OK, BAD, WARN, INFO = "  [ok]", "  [PROBLEM]", "  [warn]", "       "


def head(title: str):
    print(f"\n{title}\n" + "-" * len(title))


async def main() -> int:
    fix = "--fix" in sys.argv
    problems: list[str] = []

    head("1. Configuration")
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    guild_id = os.environ.get("DISCORD_GUILD_ID", "").strip()
    channel_id = os.environ.get("DISCORD_CHANNEL_ID", "").strip()
    owner_email = os.environ.get("DISCORD_OWNER_EMAIL", "").strip().lower()

    if not token:
        print(f"{BAD} DISCORD_BOT_TOKEN is empty - the bot is disabled entirely.")
        print(f"{INFO} Set it in selfhost/.env, then: docker compose up -d --build")
        return 1
    print(f"{OK} DISCORD_BOT_TOKEN is set ({len(token)} chars, ends ...{token[-4:]})")
    print(f"{OK if guild_id else WARN} DISCORD_GUILD_ID = {guild_id or '(not set)'}")
    print(f"{OK if channel_id else WARN} DISCORD_CHANNEL_ID = {channel_id or '(not set)'}")
    print(f"{OK if owner_email else WARN} DISCORD_OWNER_EMAIL = {owner_email or '(not set)'}")

    try:
        import discord
        from discord import app_commands
    except ImportError:
        print(f"\n{BAD} discord.py is not installed in this container.")
        print(f"{INFO} Rebuild the image: docker compose up -d --build")
        return 1

    head("2. Logging in to Discord")
    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)
    result: dict = {}

    @client.event
    async def on_ready():
        try:
            result["user"] = str(client.user)
            result["app_id"] = client.application_id
            result["guilds"] = [(g.name, g.id, g.me.guild_permissions.value if g.me else 0)
                                for g in client.guilds]
            cmds = {}
            for g in client.guilds:
                try:
                    cmds[g.id] = [c.name for c in await tree.fetch_commands(guild=g)]
                except Exception as e:  # noqa: BLE001
                    cmds[g.id] = f"could not read: {e}"
            try:
                cmds["global"] = [c.name for c in await tree.fetch_commands()]
            except Exception as e:  # noqa: BLE001
                cmds["global"] = f"could not read: {e}"
            result["commands"] = cmds
        except Exception as e:  # noqa: BLE001
            result["error"] = e
        finally:
            await client.close()

    try:
        await client.start(token)
    except Exception as e:  # noqa: BLE001
        # Close the session explicitly or aiohttp prints "Unclosed connector"
        # noise over the diagnosis we just produced.
        try:
            await client.close()
        except Exception:
            pass
        name = type(e).__name__
        print(f"{BAD} Login failed ({name}): {e}")
        if "LoginFailure" in name or "Unauthorized" in name:
            print(f"{INFO} The token was rejected. Regenerate it at")
            print(f"{INFO} discord.com/developers > your app > Bot > Reset Token.")
            print(f"{INFO} Copy the BOT token - not the Client Secret, not the App ID.")
        return 1

    if result.get("error"):
        print(f"{BAD} Connected but failed while inspecting: {result['error']}")
        return 1
    print(f"{OK} Logged in as {result['user']} (application id {result['app_id']})")

    head("3. Servers this bot can see")
    guilds = result.get("guilds") or []
    if not guilds:
        print(f"{BAD} The bot is not in ANY server.")
        print(f"{INFO} Re-invite it with BOTH scopes:")
        print(f"{INFO} https://discord.com/api/oauth2/authorize"
              f"?client_id={result['app_id']}&permissions=277025508352"
              f"&scope=bot%20applications.commands")
        return 1
    for name, gid, perms in guilds:
        print(f"{OK} {name!r}  id {gid}")
    print(f"{INFO} ^ DISCORD_GUILD_ID must be one of these ids (the SERVER id).")

    if guild_id and not any(str(g[1]) == guild_id for g in guilds):
        problems.append(
            f"DISCORD_GUILD_ID={guild_id} is not a server this bot is in. "
            f"Use one of the ids above, or clear the value to sync everywhere.")
        print(f"{BAD} DISCORD_GUILD_ID={guild_id} matches none of them.")
    elif guild_id:
        print(f"{OK} DISCORD_GUILD_ID matches a connected server.")

    head("4. Commands registered with Discord")
    cmds = result.get("commands") or {}
    any_registered = False
    for name, gid, _perms in guilds:
        got = cmds.get(gid)
        if isinstance(got, str):
            print(f"{BAD} {name!r}: {got}")
            problems.append(f"Cannot read commands in {name!r} - the invite is "
                            f"probably missing the applications.commands scope.")
        elif got:
            any_registered = True
            print(f"{OK} {name!r}: {len(got)} commands -> {', '.join(sorted(got))}")
        else:
            print(f"{BAD} {name!r}: no commands registered")
    g_cmds = cmds.get("global")
    if isinstance(g_cmds, list) and g_cmds:
        any_registered = True
        print(f"{WARN} global: {len(g_cmds)} commands (can take an hour to appear)")

    if not any_registered:
        problems.append("No commands are registered anywhere. Either the invite "
                        "lacked applications.commands, or the bot never synced.")

    if fix:
        head("5. Registering commands now (--fix)")
        print(f"{INFO} Start the backend normally; it syncs on every boot.")
        print(f"{INFO} docker compose restart backend")

    head("VERDICT")
    if not problems:
        if any_registered:
            print(f"{OK} Everything checks out. If Discord still shows nothing,")
            print(f"{INFO} fully quit and reopen the Discord client (Ctrl+R on desktop)")
            print(f"{INFO} - it caches the command list aggressively.")
            return 0
        print(f"{WARN} No obvious misconfiguration, but no commands are registered.")
        print(f"{INFO} Restart the backend and re-run this: docker compose restart backend")
        return 1

    for i, p in enumerate(problems, 1):
        print(f"{BAD} {i}. {p}")
    print()
    print(f"{INFO} Most of these are fixed by re-inviting with both scopes:")
    print(f"{INFO} https://discord.com/api/oauth2/authorize"
          f"?client_id={result['app_id']}&permissions=277025508352"
          f"&scope=bot%20applications.commands")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(130)
