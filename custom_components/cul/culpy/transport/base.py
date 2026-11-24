"""Transport interface: a line-oriented byte stream to the CUL."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from contextlib import suppress


class Transport(ABC):
    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def write_line(self, line: str) -> None: ...

    @abstractmethod
    async def read_line(self) -> str:
        """Next line without line ending. Raises ConnectionError when the link is gone."""

    @abstractmethod
    async def close(self) -> None: ...


class StreamTransport(Transport):
    """Line handling on an asyncio reader/writer pair; subclasses open the pair."""

    def __init__(self) -> None:
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def write_line(self, line: str) -> None:
        if self._writer is None:
            raise ConnectionError("not connected")
        self._writer.write(f"{line}\n".encode("ascii"))
        await self._writer.drain()

    async def read_line(self) -> str:
        if self._reader is None:
            raise ConnectionError("not connected")
        data = await self._reader.readline()
        if not data:
            raise ConnectionError("connection closed")
        return data.decode("ascii", "replace").strip()

    async def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            with suppress(Exception):
                await self._writer.wait_closed()
        self._reader = self._writer = None
