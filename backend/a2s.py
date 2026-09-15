"""Steam A2S_INFO queries - how many people are actually on a server.

Every game that registers with Steam's master server browser answers A2S on its
query port, which is exactly the `serverbrowsername` signal the library scan
uses. That makes one UDP round-trip enough to drive both the idle shutdown and
the "someone is playing, don't stop it" guard.

Servers that don't speak A2S (Palworld, Satisfactory and friends use REST or
RCON) return None rather than 0 - an unknown player count must never be
mistaken for an empty server, or the reaper would kill an occupied one.
"""
from __future__ import annotations

import asyncio
import struct
from typing import Optional

HEADER = b"\xFF\xFF\xFF\xFF"
A2S_INFO = b"\x54Source Engine Query\x00"
RESP_INFO = 0x49      # 'I' - the server info payload
RESP_CHALLENGE = 0x41  # 'A' - "retry with this challenge"

DEFAULT_TIMEOUT = 3.0


class _Reader:
    """Little-endian cursor over an A2S payload."""

    def __init__(self, data: bytes):
        self.d = data
        self.i = 0

    def byte(self) -> int:
        v = self.d[self.i]
        self.i += 1
        return v

    def short(self) -> int:
        v = struct.unpack_from("<h", self.d, self.i)[0]
        self.i += 2
        return v

    def string(self) -> str:
        end = self.d.index(b"\x00", self.i)
        v = self.d[self.i:end].decode("utf-8", "replace")
        self.i = end + 1
        return v


def parse_info(payload: bytes) -> Optional[dict]:
    """Parse an A2S_INFO response body (everything after the 0xFFFFFFFF header)."""
    if not payload or payload[0] != RESP_INFO:
        return None
    r = _Reader(payload)
    try:
        r.byte()                      # response type
        r.byte()                      # protocol version
        name = r.string()
        mapname = r.string()
        r.string()                    # folder
        game = r.string()
        r.short()                     # steam app id
        players = r.byte()
        max_players = r.byte()
        bots = r.byte()
    except (IndexError, struct.error, ValueError):
        return None
    # Bots aren't people; a server full of bots is still idle.
    return {"name": name, "map": mapname, "game": game,
            "players": max(0, players - bots), "raw_players": players,
            "max_players": max_players, "bots": bots}


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self, fut: asyncio.Future):
        self.fut = fut

    def datagram_received(self, data, addr):
        if not self.fut.done():
            self.fut.set_result(data)

    def error_received(self, exc):
        if not self.fut.done():
            self.fut.set_exception(exc)


async def _exchange(host: str, port: int, payload: bytes, timeout: float) -> bytes:
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: _Protocol(fut), remote_addr=(host, port))
    try:
        transport.sendto(payload)
        return await asyncio.wait_for(fut, timeout)
    finally:
        transport.close()


async def info(host: str, port: int, timeout: float = DEFAULT_TIMEOUT) -> Optional[dict]:
    """Query a server. Returns None when it doesn't answer or doesn't speak A2S.

    Modern servers reply to the bare query with a challenge that has to be
    echoed back, so this may take two round-trips.
    """
    try:
        data = await _exchange(host, port, HEADER + A2S_INFO, timeout)
    except (asyncio.TimeoutError, OSError):
        return None
    if len(data) < 5:
        return None

    body = data[4:]
    if body[0] == RESP_CHALLENGE:
        challenge = body[1:5]
        try:
            data = await _exchange(host, port, HEADER + A2S_INFO + challenge, timeout)
        except (asyncio.TimeoutError, OSError):
            return None
        if len(data) < 5:
            return None
        body = data[4:]
    return parse_info(body)


async def player_count(host: str, port: int,
                       timeout: float = DEFAULT_TIMEOUT) -> Optional[int]:
    """Human players online, or None if the server can't be asked."""
    d = await info(host, port, timeout)
    return None if d is None else d["players"]
