"""In-memory transport for tests and dry runs."""

from __future__ import annotations

import asyncio

from .base import Transport


class FakeTransport(Transport):
    def __init__(self, answers: dict[str, str] | None = None, connect_failures: int = 0) -> None:
        self.answers = dict(answers or {})
        self.connect_failures = connect_failures
        self.written: list[str] = []
        self.connects = 0
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def connect(self) -> None:
        self.connects += 1
        if self.connect_failures > 0:
            self.connect_failures -= 1
            raise ConnectionError("fake connect failure")

    async def write_line(self, line: str) -> None:
        self.written.append(line)
        answer = self.answers.get(line)
        if answer is not None:
            self._queue.put_nowait(answer)

    def feed(self, line: str) -> None:
        self._queue.put_nowait(line)

    def drop(self) -> None:
        self._queue.put_nowait(None)

    async def read_line(self) -> str:
        item = await self._queue.get()
        if item is None:
            raise ConnectionError("fake drop")
        return item

    async def close(self) -> None:
        return None
