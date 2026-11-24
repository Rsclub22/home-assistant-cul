"""Protocol plumbing: events, handler interface, dispatcher."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from ..frame import Frame

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DeviceEvent:
    """Decoded values from one RF message."""

    protocol: str
    address: str
    values: dict[str, Any]
    rssi: float | None = None


class ProtocolHandler(Protocol):
    """One culfw protocol (FHT, FHT80TF, …)."""

    name: str

    def accepts(self, frame: Frame) -> bool: ...

    def decode(self, frame: Frame) -> DeviceEvent | None: ...


class Dispatcher:
    """Hand each frame to the first handler that accepts it."""

    def __init__(self, handlers: list[ProtocolHandler]) -> None:
        self._handlers = list(handlers)
        self.dropped = 0

    def dispatch(self, frame: Frame) -> DeviceEvent | None:
        for handler in self._handlers:
            if handler.accepts(frame):
                return handler.decode(frame)
        self.dropped += 1
        _LOGGER.debug("No protocol for frame %s%s", frame.kind, frame.payload)
        return None
