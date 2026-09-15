"""Tests for A2S player-count queries, including against a real local UDP socket."""
import asyncio
import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import a2s  # noqa: E402


def make_info(name="Jeff's ARK", mapname="TheIsland", game="ARK",
              players=3, max_players=20, bots=0) -> bytes:
    """Build an A2S_INFO response body the way a real server would."""
    b = bytearray()
    b.append(a2s.RESP_INFO)
    b.append(17)                                  # protocol
    for s in (name, mapname, "ark", game):
        b += s.encode() + b"\x00"
    b += struct.pack("<H", 346110 & 0xFFFF)       # app id, truncated to 16 bits
    b += bytes([players, max_players, bots])
    b += b"d\x00w\x001.0\x00"                     # type, env, visibility, version
    return bytes(b)


# --------------------------------------------------------------- parsing ---
def test_parses_a_normal_response():
    d = a2s.parse_info(make_info(players=3, max_players=20))
    assert d["name"] == "Jeff's ARK"
    assert d["map"] == "TheIsland"
    assert d["players"] == 3
    assert d["max_players"] == 20


def test_bots_are_not_counted_as_players():
    """A server full of bots is still idle - it must be allowed to shut down."""
    d = a2s.parse_info(make_info(players=8, bots=8))
    assert d["raw_players"] == 8
    assert d["players"] == 0


def test_empty_server_reports_zero():
    assert a2s.parse_info(make_info(players=0))["players"] == 0


def test_rejects_a_non_info_payload():
    assert a2s.parse_info(b"\x41\x01\x02\x03\x04") is None
    assert a2s.parse_info(b"") is None


def test_truncated_payload_does_not_raise():
    assert a2s.parse_info(make_info()[:6]) is None


def test_handles_utf8_server_names():
    assert a2s.parse_info(make_info(name="Jeff's ARK — main"))["name"] == "Jeff's ARK — main"


# ------------------------------------------------------- live UDP socket ---
class FakeServer(asyncio.DatagramProtocol):
    """A minimal A2S responder, optionally doing the challenge handshake."""

    def __init__(self, body: bytes, challenge: bool = False):
        self.body = body
        self.challenge = challenge
        self.seen = []

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        self.seen.append(data)
        if self.challenge and len(data) <= len(a2s.HEADER + a2s.A2S_INFO):
            self.transport.sendto(a2s.HEADER + bytes([a2s.RESP_CHALLENGE]) + b"\x01\x02\x03\x04", addr)
            return
        self.transport.sendto(a2s.HEADER + self.body, addr)


async def serve(body, challenge=False):
    loop = asyncio.get_running_loop()
    transport, proto = await loop.create_datagram_endpoint(
        lambda: FakeServer(body, challenge), local_addr=("127.0.0.1", 0))
    return transport, proto, transport.get_extra_info("sockname")[1]


async def test_queries_a_live_server():
    transport, _proto, port = await serve(make_info(players=5))
    try:
        assert await a2s.player_count("127.0.0.1", port) == 5
    finally:
        transport.close()


async def test_completes_the_challenge_handshake():
    """Modern servers demand a challenge echo before answering."""
    transport, proto, port = await serve(make_info(players=2), challenge=True)
    try:
        assert await a2s.player_count("127.0.0.1", port) == 2
        assert len(proto.seen) == 2                      # bare query, then with challenge
        assert proto.seen[1].endswith(b"\x01\x02\x03\x04")
    finally:
        transport.close()


async def test_unreachable_server_returns_none_not_zero():
    """The critical distinction: unknown must never look like empty."""
    assert await a2s.player_count("127.0.0.1", 1, timeout=0.4) is None


async def test_silent_server_times_out_to_none():
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        asyncio.DatagramProtocol, local_addr=("127.0.0.1", 0))
    try:
        port = transport.get_extra_info("sockname")[1]
        assert await a2s.player_count("127.0.0.1", port, timeout=0.4) is None
    finally:
        transport.close()


async def test_garbage_response_returns_none():
    transport, _proto, port = await serve(b"\x99nonsense")
    try:
        assert await a2s.player_count("127.0.0.1", port, timeout=1.0) is None
    finally:
        transport.close()
