"""Serial transport: CUL directly on USB or UART."""

from __future__ import annotations

import asyncio

from .base import StreamTransport

DEFAULT_BAUDRATE = 9600  # the USB CUL ignores it; a CUL on a UART (COC) usually needs 38400


class SerialTransport(StreamTransport):
    def __init__(self, device: str, baudrate: int = DEFAULT_BAUDRATE,
                 connect_timeout: float = 10.0) -> None:
        super().__init__()
        self.device, self.baudrate, self._timeout = device, baudrate, connect_timeout

    async def connect(self) -> None:
        # imported here: culpy itself must stay usable without serialx
        from serialx import SerialException, open_serial_connection

        try:
            self._reader, self._writer = await asyncio.wait_for(
                open_serial_connection(self.device, baudrate=self.baudrate), self._timeout)
        except SerialException as err:
            # the connection loop and the config flow only handle OSError/ConnectionError
            raise ConnectionError(f"{self.device}: {err}") from err
