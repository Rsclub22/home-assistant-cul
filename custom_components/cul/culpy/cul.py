"""CUL core: connection, culfw init, queries, RF dispatch, reconnect."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass

from .frame import parse_rf_line
from .protocols.base import DeviceEvent, Dispatcher, ProtocolHandler
from .protocols.fht import FhtProtocol
from .protocols.fhttk import FhtTkProtocol
from .transport.base import Transport

_LOGGER = logging.getLogger(__name__)

RE_VERSION = r"^V "
RE_FHTID = r"^[0-9A-F]{4}$"
RE_FHTBUF = r"^[0-9A-F]{2}$"
RE_CREDIT = r"^[0-9A-F]{2} +\d+$"


@dataclass
class CulState:
    connected: bool = False
    version: str | None = None
    fhtid: str | None = None
    fhtbuf: int | None = None
    credit10ms: int | None = None
    dropped: int = 0
    lovf: bool = False


class Cul:
    def __init__(
        self,
        transport_factory: Callable[[], Transport],
        *,
        fhtid: str | None = None,
        handlers: list[ProtocolHandler] | None = None,
        on_event: Callable[[DeviceEvent], None] | None = None,
        on_state: Callable[[CulState], None] | None = None,
        reconnect_min: float = 1.0,
        reconnect_max: float = 60.0,
        query_timeout: float = 3.0,
        idle_timeout: float = 300.0,
    ) -> None:
        self._factory = transport_factory
        self._fhtid = fhtid.upper() if fhtid else None
        self._dispatcher = Dispatcher(handlers or [FhtProtocol(), FhtTkProtocol()])
        self._on_event = on_event
        self._on_state = on_state
        self._rmin, self._rmax, self._qtimeout = reconnect_min, reconnect_max, query_timeout
        self._idle_timeout = idle_timeout
        self._last_rx = 0.0
        self.state = CulState()
        self._transport: Transport | None = None
        self._task: asyncio.Task | None = None
        self._stopping = False
        self._initializing = False
        self._query_lock = asyncio.Lock()
        self._pending: tuple[re.Pattern[str], asyncio.Future[str]] | None = None

    async def start(self) -> None:
        self._stopping = False
        self._task = asyncio.create_task(self._run(), name="culpy-run")

    async def stop(self) -> None:
        self._stopping = True
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        self._task = None

    async def write(self, line: str) -> None:
        if self._transport is None or (not self.state.connected and not self._initializing):
            raise ConnectionError("CUL not connected")
        _LOGGER.debug("-> %s", line)
        await self._transport.write_line(line)

    async def query(self, command: str, pattern: str) -> str:
        async with self._query_lock:
            fut: asyncio.Future[str] = asyncio.get_running_loop().create_future()
            self._pending = (re.compile(pattern), fut)
            try:
                await self.write(command)
                return await asyncio.wait_for(fut, self._qtimeout)
            finally:
                self._pending = None

    async def refresh_status(self) -> None:
        self.state.fhtbuf = int(await self.query("T03", RE_FHTBUF), 16)
        self.state.credit10ms = int((await self.query("X", RE_CREDIT)).split()[1])
        if self.state.credit10ms > 0:
            self.state.lovf = False
        self._notify()

    def _notify(self) -> None:
        if self._on_state:
            self._on_state(self.state)

    async def _run(self) -> None:
        delay = self._rmin
        while not self._stopping:
            transport = self._factory()
            reader: asyncio.Task | None = None
            try:
                await transport.connect()
                self._transport = transport
                reader = asyncio.create_task(self._read_loop(transport), name="culpy-read")
                await self._initialize()
                self.state.connected = True
                self._notify()
                delay = self._rmin
                await self._watch(reader)
            except (ConnectionError, OSError, TimeoutError) as err:
                _LOGGER.warning("CUL connection problem: %s", err)
            except Exception:
                _LOGGER.exception("Unexpected error in CUL connection loop")
            finally:
                if reader and not reader.done():
                    reader.cancel()
                    with suppress(asyncio.CancelledError, ConnectionError):
                        await reader
                with suppress(Exception):
                    await transport.close()
                self._transport = None
                if self.state.connected:
                    self.state.connected = False
                    self._notify()
            if self._stopping:
                break
            await asyncio.sleep(delay)
            delay = min(delay * 2, self._rmax)

    async def _watch(self, reader: asyncio.Task) -> None:
        """Wait for the reader; after idle_timeout without any line ask for the version.

        A half-open TCP connection (cable pulled, ser2net host gone) never ends the reader,
        so silence is checked here, outside the reader that resolves the query answer.
        """
        loop = asyncio.get_running_loop()
        self._last_rx = loop.time()
        while True:
            remaining = self._last_rx + self._idle_timeout - loop.time()
            if remaining > 0:
                await asyncio.wait({reader}, timeout=remaining)
                if reader.done():
                    await reader  # raises the reader's ConnectionError
                    return
                continue
            try:
                await self.query("V", RE_VERSION)
            except TimeoutError as err:
                raise ConnectionError(
                    f"no answer from CUL after {self._idle_timeout:.0f} s silence") from err
            self._last_rx = loop.time()

    async def _initialize(self) -> None:
        self._initializing = True
        try:
            self.state.version = await self.query("V", RE_VERSION)
            await self.write("X21")
            if self._fhtid:
                current = await self.query("T01", RE_FHTID)
                if current.upper() != self._fhtid:
                    _LOGGER.warning("CUL FHT-ID %s, setting %s", current, self._fhtid)
                    await self.write(f"T01{self._fhtid}")
                self.state.fhtid = self._fhtid
            await self.refresh_status()
        finally:
            self._initializing = False

    async def _read_loop(self, transport: Transport) -> None:
        while True:
            line = await transport.read_line()
            self._last_rx = asyncio.get_running_loop().time()
            self._handle_line(line)

    def _handle_line(self, line: str) -> None:
        try:
            self._process_line(line)
        except Exception:
            _LOGGER.exception("Error handling CUL line %r", line)

    def _process_line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        _LOGGER.debug("<- %s", line)
        if self._pending and not self._pending[1].done() and self._pending[0].match(line):
            self._pending[1].set_result(line)
            return
        if line == "LOVF":
            self.state.lovf = True
            self._notify()
            return
        if line == "EOB":
            self.state.fhtbuf = 0
            self._notify()
            return
        frame = parse_rf_line(line)
        if frame is None:
            _LOGGER.debug("Ignoring line %r", line)
            return
        event = self._dispatcher.dispatch(frame)
        if self._dispatcher.dropped != self.state.dropped:
            self.state.dropped = self._dispatcher.dropped
            self._notify()
        if event is not None and self._on_event:
            self._on_event(event)


async def probe(transport: Transport, timeout: float = 5.0) -> tuple[str, str | None]:  # noqa: ASYNC109
    """Connect once, read version and FHT-ID without changing anything."""

    async def answer(command: str, pattern: str) -> str:
        await transport.write_line(command)
        regex = re.compile(pattern)
        while True:
            line = (await transport.read_line()).strip()
            if regex.match(line):
                return line

    await transport.connect()
    try:
        async with asyncio.timeout(timeout):
            version = await answer("V", RE_VERSION)
            fhtid = await answer("T01", RE_FHTID)
    finally:
        await transport.close()
    return version, (None if fhtid == "0000" else fhtid)
