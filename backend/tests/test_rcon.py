"""Tests for the RCON save path, against a real local TCP socket."""
import asyncio
import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rcon  # noqa: E402

PASSWORD = "hunter2"


# --------------------------------------------------------------- codec ----
def test_encode_decode_roundtrip():
    packet = rcon.encode(7, rcon.EXEC, "saveworld")
    (size,) = struct.unpack("<i", packet[:4])
    assert size == len(packet) - 4
    assert rcon.decode(packet[4:]) == (7, rcon.EXEC, "saveworld")


def test_decode_rejects_short_packet():
    with pytest.raises(rcon.RconError):
        rcon.decode(b"\x01\x02")


# ---------------------------------------------------------- fake server ---
async def fake_rcon(reader, writer, *, password=PASSWORD, reply="World Saved",
                    chatty=False):
    async def read():
        (size,) = struct.unpack("<i", await reader.readexactly(4))
        return rcon.decode(await reader.readexactly(size))

    try:
        req_id, _kind, body = await read()
        if body != password:
            writer.write(rcon.encode(rcon.AUTH_FAILED, rcon.EXEC, ""))
            await writer.drain()
            return
        if chatty:  # some servers send a junk value before the auth result
            writer.write(rcon.encode(req_id, rcon.RESPONSE, ""))
        writer.write(rcon.encode(req_id, rcon.EXEC, ""))
        await writer.drain()

        _rid, _k, command = await read()
        writer.write(rcon.encode(2, rcon.RESPONSE, f"{reply} [{command}]"))
        await writer.drain()
    except (asyncio.IncompleteReadError, ConnectionResetError):
        pass
    finally:
        writer.close()


async def serve(**kw):
    server = await asyncio.start_server(
        lambda r, w: fake_rcon(r, w, **kw), "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


# --------------------------------------------------------------- happy ----
async def test_executes_a_command():
    server, port = await serve()
    async with server:
        out = await rcon.execute("127.0.0.1", port, PASSWORD, "saveworld")
    assert "World Saved" in out and "saveworld" in out


async def test_tolerates_a_junk_packet_before_auth_response():
    server, port = await serve(chatty=True)
    async with server:
        ok, msg = await rcon.save_world("127.0.0.1", port, PASSWORD, "saveworld")
    assert ok and "World Saved" in msg


async def test_save_world_reports_success():
    server, port = await serve(reply="Saving...done")
    async with server:
        ok, msg = await rcon.save_world("127.0.0.1", port, PASSWORD, "save")
    assert ok and "done" in msg


# --------------------------------------------------------------- sad ------
async def test_wrong_password_is_reported_not_raised():
    server, port = await serve()
    async with server:
        ok, msg = await rcon.save_world("127.0.0.1", port, "wrong", "saveworld")
    assert not ok and "rejected" in msg


async def test_unreachable_rcon_does_not_raise():
    """A failed save must never block the shutdown - just report it."""
    ok, msg = await rcon.save_world("127.0.0.1", 1, PASSWORD, "saveworld", timeout=0.5)
    assert not ok and "cannot reach" in msg


async def test_execute_raises_on_unreachable_host():
    with pytest.raises(rcon.RconError):
        await rcon.execute("127.0.0.1", 1, PASSWORD, "saveworld", timeout=0.5)
