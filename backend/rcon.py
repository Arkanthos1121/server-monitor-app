"""Source RCON client - used to save a world before shutting a server down.

SIGTERM makes most engines save on the way out, but "most" is not good enough
when someone's base is on the line. Where a game exposes RCON, an explicit save
command is sent and acknowledged first, so the shutdown only proceeds once the
world is on disk.
"""
from __future__ import annotations

import asyncio
import struct
from typing import Optional

AUTH = 3               # SERVERDATA_AUTH
EXEC = 2               # SERVERDATA_EXECCOMMAND / SERVERDATA_AUTH_RESPONSE
RESPONSE = 0           # SERVERDATA_RESPONSE_VALUE
AUTH_FAILED = -1

DEFAULT_TIMEOUT = 10.0
MAX_PACKET = 4096


class RconError(Exception):
    pass


def encode(req_id: int, kind: int, body: str) -> bytes:
    payload = struct.pack("<ii", req_id, kind) + body.encode("utf-8") + b"\x00\x00"
    return struct.pack("<i", len(payload)) + payload


def decode(packet: bytes) -> tuple[int, int, str]:
    """Decode one packet body (already stripped of its leading size field)."""
    if len(packet) < 8:
        raise RconError("short packet")
    req_id, kind = struct.unpack_from("<ii", packet, 0)
    body = packet[8:].split(b"\x00", 1)[0].decode("utf-8", "replace")
    return req_id, kind, body


async def _read_packet(reader: asyncio.StreamReader) -> tuple[int, int, str]:
    raw = await reader.readexactly(4)
    (size,) = struct.unpack("<i", raw)
    if size < 8 or size > MAX_PACKET:
        raise RconError(f"implausible packet size {size}")
    return decode(await reader.readexactly(size))


async def execute(host: str, port: int, password: str, command: str,
                  timeout: float = DEFAULT_TIMEOUT) -> str:
    """Authenticate, run one command, return the server's reply text."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout)
    except (OSError, asyncio.TimeoutError) as e:
        raise RconError(f"cannot reach RCON at {host}:{port} ({e})") from e

    try:
        writer.write(encode(1, AUTH, password))
        await writer.drain()

        # Some servers emit an empty RESPONSE_VALUE before the auth result.
        for _ in range(2):
            req_id, kind, _body = await asyncio.wait_for(_read_packet(reader), timeout)
            if kind == EXEC:
                break
        else:
            raise RconError("no auth response")
        if req_id == AUTH_FAILED:
            raise RconError("RCON password rejected")

        writer.write(encode(2, EXEC, command))
        await writer.drain()
        _rid, _kind, body = await asyncio.wait_for(_read_packet(reader), timeout)
        return body
    except asyncio.IncompleteReadError as e:
        raise RconError("connection closed mid-exchange") from e
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def save_world(host: str, port: int, password: str, command: str,
                     timeout: float = DEFAULT_TIMEOUT) -> tuple[bool, str]:
    """Best-effort save. Never raises - a failed save must not block a shutdown,
    it just has to be reported honestly."""
    try:
        reply = await execute(host, port, password, command, timeout)
        return True, (reply.strip() or f"'{command}' acknowledged")
    except RconError as e:
        return False, str(e)
    except Exception as e:  # noqa: BLE001 - shutdown path must stay alive
        return False, f"unexpected RCON failure: {e}"
