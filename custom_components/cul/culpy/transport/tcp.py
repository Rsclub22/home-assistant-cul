"""Raw TCP transport (ser2net)."""

from __future__ import annotations

import asyncio
import socket

from .base import StreamTransport


def _enable_keepalive(sock) -> None:
    """Let the kernel notice a dead peer (~90 s) in addition to the CUL heartbeat."""
    if sock is None:
        return
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    for name, value in (("TCP_KEEPIDLE", 60), ("TCP_KEEPINTVL", 10), ("TCP_KEEPCNT", 3)):
        if hasattr(socket, name):
            sock.setsockopt(socket.IPPROTO_TCP, getattr(socket, name), value)


class TcpTransport(StreamTransport):
    def __init__(self, host: str, port: int, connect_timeout: float = 10.0) -> None:
        super().__init__()
        self.host, self.port, self._timeout = host, port, connect_timeout

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port), self._timeout
        )
        _enable_keepalive(self._writer.get_extra_info("socket"))
