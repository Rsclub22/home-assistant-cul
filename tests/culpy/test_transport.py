"""Transport tests."""

import asyncio

import pytest

from custom_components.cul.culpy.transport.fake import FakeTransport
from custom_components.cul.culpy.transport.tcp import TcpTransport

pytestmark = pytest.mark.usefixtures("socket_enabled")


async def test_fake_answers_and_feed():
    t = FakeTransport({"V": "V 1.67 CUL868"})
    await t.connect()
    await t.write_line("V")
    assert await t.read_line() == "V 1.67 CUL868"
    t.feed("T1C50416928AA")
    assert await t.read_line() == "T1C50416928AA"
    assert t.written == ["V"]
    t.drop()
    with pytest.raises(ConnectionError):
        await t.read_line()


async def test_fake_connect_failures():
    t = FakeTransport(connect_failures=1)
    with pytest.raises(ConnectionError):
        await t.connect()
    await t.connect()
    assert t.connects == 2


async def test_tcp_roundtrip():
    received: list[bytes] = []

    async def handle(reader, writer):
        received.append(await reader.readline())
        writer.write(b"V 1.67 CUL868\r\n")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    t = TcpTransport("127.0.0.1", port)
    await t.connect()
    await t.write_line("V")
    assert await t.read_line() == "V 1.67 CUL868"
    with pytest.raises(ConnectionError):
        await t.read_line()
    await t.close()
    server.close()
    await server.wait_closed()
    assert received == [b"V\n"]


async def test_tcp_enables_keepalive():
    import socket

    async def handle(reader, writer):
        await reader.read()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    t = TcpTransport("127.0.0.1", port)
    await t.connect()
    sock = t._writer.get_extra_info("socket")
    assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE)
    if hasattr(socket, "TCP_KEEPIDLE"):
        assert sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE) == 60
        assert sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL) == 10
        assert sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT) == 3
    await t.close()
    server.close()
    await server.wait_closed()


async def test_serial_roundtrip_over_pty():
    import os
    import pty

    from custom_components.cul.culpy.transport.serial import SerialTransport

    master, slave = pty.openpty()
    t = SerialTransport(os.ttyname(slave))
    try:
        await t.connect()
        await t.write_line("V")
        loop = asyncio.get_running_loop()
        assert await loop.run_in_executor(None, os.read, master, 16) == b"V\n"
        os.write(master, b"V 1.67 CUL868\r\n")
        assert await asyncio.wait_for(t.read_line(), 5) == "V 1.67 CUL868"
    finally:
        await t.close()
        os.close(master)
        os.close(slave)


async def test_serial_missing_device_is_connection_error():
    from custom_components.cul.culpy.transport.serial import SerialTransport

    with pytest.raises((ConnectionError, OSError)):
        await SerialTransport("/dev/does-not-exist").connect()
