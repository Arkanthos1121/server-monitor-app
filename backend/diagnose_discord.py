"""One-shot Discord diagnosis. Run it, read the verdict, do what it says.

    docker compose exec backend python3 diagnose_discord.py

Checks the config, proves the container can actually reach Discord, logs in with
your real token, lists the guilds the bot can see, and asks Discord which
commands are registered where. It changes nothing.

Every step prints as it happens and every wait prints its elapsed seconds, so a
slow step is distinguishable from a hung one. Nothing here waits more than 30s.
"""
from __future__ import annotations

import asyncio
import os
import socket
import sys
import time

OK, BAD, WARN, INFO = "  [ok]", "  [PROBLEM]", "  [warn]", "       "

# discord.py needs all three: REST to log in, the gateway to stay connected,
# and the CDN only for avatars. The first two are what break behind a firewall.
REST_HOST, GATEWAY_HOST = "discord.com", "gateway.discord.gg"

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass


def head(title: str):
    print(f"\n{title}\n" + "-" * len(title), flush=True)


async def ticking(label: str, stop: asyncio.Event, every: float = 3.0):
    """Print elapsed seconds while something slow runs.

    Without this a stalled network call is indistinguishable from a hung
    script, and people Ctrl+C out before the timeout ever fires.
    """
    t0 = time.monotonic()
    while True:
        try:
            await asyncio.wait_for(stop.wait(), timeout=every)
            return
        except asyncio.TimeoutError:
            print(f"{INFO}   {int(time.monotonic() - t0)}s - still {label}", flush=True)


async def with_ticker(label: str, coro, timeout: float):
    """Await coro with a visible heartbeat and a hard ceiling."""
    stop = asyncio.Event()
    tick = asyncio.create_task(ticking(label, stop))
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    finally:
        stop.set()
        tick.cancel()
        try:
            await tick
        except BaseException:
            pass


async def resolves(host: str) -> tuple[str, str]:
    """(ip, error). DNS is the first thing to die in a container."""
    loop = asyncio.get_running_loop()
    try:
        infos = await with_ticker(
            f"resolving {host}",
            loop.getaddrinfo(host, 443, type=socket.SOCK_STREAM), timeout=10)
        return infos[0][4][0], ""
    except BaseException as e:   # noqa: BLE001
        return "", f"{type(e).__name__}: {e}"


async def connects(host: str, port: int = 443) -> str:
    """"" on success, else the error. A plain TCP open, same as discord.py."""
    try:
        reader, writer = await with_ticker(
            f"connecting to {host}:{port}",
            asyncio.open_connection(host, port), timeout=15)
        del reader
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return ""
    except BaseException as e:   # noqa: BLE001
        return f"{type(e).__name__}: {e}"


def report_channels(chans: list, channel_id: str, problems: list) -> None:
    """Section 6, split out so its logic is testable without a live login."""
    usable = [c for c in chans if c["view"] and c["use_cmds"]]
    if not chans:
        print(f"{WARN} Could not read channel permissions.")
    elif not usable:
        print(f"{BAD} The bot cannot use commands in ANY channel.")
        print(f"{INFO} Its role is denied 'View Channel' or 'Use Application")
        print(f"{INFO} Commands' server-wide. Fix it in Server Settings > Roles.")
        problems.append("The bot has no channel it can be used in, so its "
                        "commands never appear however well they are registered.")
    else:
        shown = ", ".join("#" + c["name"] for c in usable[:12])
        print(f"{OK} {len(usable)} usable channel(s): {shown}")
        blocked = [c for c in chans if c not in usable]
        if blocked:
            print(f"{WARN} not usable: " + ", ".join("#" + c["name"] for c in blocked[:12]))
            print(f"{INFO} Typing / in those will offer nothing. Right-click the")
            print(f"{INFO} channel > Edit Channel > Permissions and allow the bot's")
            print(f"{INFO} role to View Channel and Use Application Commands.")

    if channel_id:
        match = [c for c in chans if str(c["id"]) == channel_id]
        if not match:
            print(f"{BAD} DISCORD_CHANNEL_ID={channel_id} is not a text channel "
                  f"this bot can see.")
            problems.append(f"DISCORD_CHANNEL_ID={channel_id} is not visible to the "
                            f"bot - auto-stop warnings will go nowhere. Use a channel "
                            f"id from the list above.")
        else:
            c = match[0]
            ok_here = c["view"] and c["use_cmds"]
            print(f"{OK if ok_here else BAD} DISCORD_CHANNEL_ID is #{c['name']} "
                  f"(view={c['view']}, send={c['send']}, commands={c['use_cmds']})")
            if not ok_here:
                problems.append(f"The bot cannot use commands in #{c['name']}, the "
                                f"channel you configured. Allow its role to View "
                                f"Channel and Use Application Commands there.")


async def main() -> int:
    problems: list[str] = []

    head("1. Configuration")
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    guild_id = os.environ.get("DISCORD_GUILD_ID", "").strip()
    channel_id = os.environ.get("DISCORD_CHANNEL_ID", "").strip()
    owner_email = os.environ.get("DISCORD_OWNER_EMAIL", "").strip().lower()

    if not token:
        print(f"{BAD} DISCORD_BOT_TOKEN is empty - the bot is disabled entirely.")
        others = [k for k in ("JWT_SECRET", "SERVER_ENC_KEY", "MONGO_URL")
                  if not os.environ.get(k, "").strip()]
        if "JWT_SECRET" in others and "SERVER_ENC_KEY" in others:
            print(f"{BAD} JWT_SECRET and SERVER_ENC_KEY are ALSO empty.")
            print(f"{INFO} That pattern means .env was overwritten with .env.example")
            print(f"{INFO} (`cp .env.example .env` over a live file). Recover the old")
            print(f"{INFO} values before regenerating - SERVER_ENC_KEY decrypts stored")
            print(f"{INFO} passwords and a new one cannot read what the old one wrote:")
            print(f"{INFO}   docker ps -a | grep backend      # an older container?")
            print(f"{INFO}   docker inspect <id> --format '{{{{range .Config.Env}}}}{{{{println .}}}}{{{{end}}}}'")
        else:
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
    print(f"{OK} discord.py {discord.__version__} is installed")

    # --------------------------------------------------------------------
    # Reachability first. A login attempt against a blocked network looks
    # exactly like a bad token from the outside, and takes far longer to fail.
    head("2. Can this container reach Discord?")
    for host in (REST_HOST, GATEWAY_HOST):
        ip, err = await resolves(host)
        if err:
            print(f"{BAD} cannot resolve {host} - {err}")
            print(f"{INFO} DNS is broken inside the container, so no login can work.")
            print(f"{INFO} Check the host first:  getent hosts {host}")
            print(f"{INFO} If the host resolves but the container does not, restart")
            print(f"{INFO} Docker's DNS:  sudo systemctl restart docker")
            return 1
        print(f"{OK} {host} resolves to {ip}")
        err = await connects(host)
        if err:
            print(f"{BAD} cannot open a TCP connection to {host}:443 - {err}")
            print(f"{INFO} DNS works but traffic is blocked. Usual causes:")
            print(f"{INFO}  - an egress firewall on this box or your router")
            print(f"{INFO}  - a proxy the container is not configured to use")
            print(f"{INFO} Compare from the host:  curl -sS -o /dev/null -w '%{{http_code}}\\n' https://{host}/api/v10/gateway")
            return 1
        print(f"{OK} TCP 443 to {host} is open")

    # --------------------------------------------------------------------
    head("3. Logging in to Discord")
    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)
    result: dict = {}

    async def inspect():
        """Gather everything once the gateway is ready."""
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

        # Guild-level registration is not enough: a command only appears in a
        # channel the bot can actually see. This is invisible from the guild
        # view and is a common reason /commands stay missing after a good sync.
        chans = []
        for g in client.guilds:
            me = g.me
            for ch in getattr(g, "text_channels", []):
                perms = ch.permissions_for(me) if me else None
                if perms is None:
                    continue
                chans.append({
                    "guild": g.name, "id": ch.id, "name": ch.name,
                    "view": perms.view_channel,
                    "send": perms.send_messages,
                    "use_cmds": getattr(perms, "use_application_commands", True),
                })
        result["channels"] = chans

    print(f"{INFO} authenticating, then waiting for the gateway (30s ceiling)")
    login_task = asyncio.create_task(client.start(token))
    stop_tick = asyncio.Event()
    tick = asyncio.create_task(ticking("waiting for Discord", stop_tick))
    t0 = time.monotonic()
    try:
        # Whichever finishes first: the gateway becomes ready, or start() blows
        # up with a login error. Waiting only on wait_until_ready() would hang
        # forever on a bad token.
        ready = asyncio.create_task(client.wait_until_ready())
        done, _pending = await asyncio.wait(
            {ready, login_task}, timeout=30, return_when=asyncio.FIRST_COMPLETED)

        if login_task in done:
            login_task.result()                      # re-raises the real error
            raise RuntimeError("the client disconnected before becoming ready")
        if ready not in done:
            raise TimeoutError("timed out waiting for the Discord gateway")

        await with_ticker("reading commands from Discord", inspect(), timeout=30)
    except BaseException as e:   # noqa: BLE001 - CancelledError is not Exception
        name = type(e).__name__
        waited = int(time.monotonic() - t0)
        if name == "KeyboardInterrupt":
            print(f"{WARN} Interrupted after {waited}s, before any verdict.")
            print(f"{INFO} Nothing is wrong yet - it was still waiting. Re-run and")
            print(f"{INFO} let it finish; it gives up on its own after 30s.")
            return 130
        print(f"{BAD} Login failed after {waited}s ({name}): {e}", flush=True)
        if "LoginFailure" in name or "Unauthorized" in name:
            print(f"{INFO} The token was rejected. Regenerate it at")
            print(f"{INFO} discord.com/developers > your app > Bot > Reset Token.")
            print(f"{INFO} Copy the BOT token - not the Client Secret, not the App ID.")
        elif "Timeout" in name:
            print(f"{INFO} The network checks above passed, so this is Discord's")
            print(f"{INFO} gateway refusing to finish the handshake. Almost always")
            print(f"{INFO} a session-start limit from restarting the bot repeatedly:")
            print(f"{INFO} wait 10 minutes and re-run. If it persists, reset the")
            print(f"{INFO} token (that clears the bot's sessions too).")
        elif "PrivilegedIntents" in name:
            print(f"{INFO} Enable the intents under Bot > Privileged Gateway Intents,")
            print(f"{INFO} or leave them off - this bot needs none.")
        return 1
    finally:
        stop_tick.set()
        tick.cancel()
        try:
            await tick
        except BaseException:
            pass
        try:
            await client.close()
        except Exception:
            pass
        if not login_task.done():
            login_task.cancel()
        try:
            await login_task
        except BaseException:
            pass

    print(f"{OK} Logged in as {result['user']} (application id {result['app_id']})")

    head("4. Servers this bot can see")
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

    head("5. Commands registered with Discord")
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

    head("6. Channels the bot can be used in")
    report_channels(result.get("channels") or [], channel_id, problems)

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
        print("\n       Interrupted. Re-run and let it finish - it times out on "
              "its own.", flush=True)
        sys.exit(130)
