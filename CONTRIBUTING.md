# Contributing

Thanks for helping! Bug reports, device logs and pull requests are welcome.

## Reporting a bug

Open an [issue](https://github.com/Rsclub22/home-assistant-cul/issues) with:

- Home Assistant version, integration version and culfw version (the CUL's `V` answer, shown on the CUL device).
- How the CUL is connected: USB or ser2net.
- A debug log of the problem (see *Troubleshooting* in the README). Remove anything private first.

Raw telegrams (`<- T…` lines) are the most useful thing for new devices or decoding errors.

## Development

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/).

```bash
uv venv --python 3.14
uv pip install -r requirements_test.txt
.venv/bin/ruff check .
.venv/bin/pytest -q
```

Layout:

- `custom_components/cul/culpy/` – protocol library without Home Assistant: transports (TCP, serial, fake), frame parsing, FHT/FHT80TF decoding, send queue.
- `custom_components/cul/` – the Home Assistant integration on top of it.
- `tests/culpy/` and `tests/ha/` – tests for both. `tests/culpy/fixtures/golden.jsonl` holds real telegrams with the values FHEM decoded from them.

## Adding a device type

culfw speaks many more protocols than FHT: FS20, FHT8V, EM, HMS, S300TH, Intertechno and others. Each protocol is a small module, so new ones can be added without touching the rest.

### 1. Collect telegrams

Without hardware there is nothing to test against. If you own the device, open an issue first with:

- the device model and what it does (sensor, switch, thermostat …);
- a debug log (see the README) with the raw lines `<- …` while you use the device: switch it, open/close it, let it report;
- what the device showed at that moment (temperature, state …).

If you run FHEM in parallel, its decoded readings for the same telegrams are gold: they become test fixtures like `tests/culpy/fixtures/golden.jsonl`.

The CUL only reports what its reporting mode lets through. The integration sets `X21`; some protocols need another mode (culfw command reference: <http://culfw.de/commandref.html>).

### 2. Decode: `culpy/protocols/`

Add a module with a class that follows `ProtocolHandler` in `culpy/protocols/base.py`:

```python
class Fs20Protocol:
    name = "fs20"

    def accepts(self, frame: Frame) -> bool:
        return frame.kind == "F" and ...

    def decode(self, frame: Frame) -> DeviceEvent | None:
        return DeviceEvent("fs20", address, {"state": "on"}, frame.rssi)
```

- `accepts()` must be strict: frames of different protocols can look alike (see the note in `fhttk.py`). Unknown frames are better dropped than turned into phantom devices.
- `decode()` returns plain Python values. No Home Assistant imports in `culpy/`.
- Register the handler in the `Dispatcher` list in `culpy/cul.py`.
- Add tests in `tests/culpy/` with real telegrams.

`fhttk.py` is the smallest complete example.

### 3. Entities: `custom_components/cul/`

- Name and model for the device: `MODELS` and `NAMES` in `entity.py`.
- Entities per platform: add an entry for your protocol to `DESCRIPTIONS` in `sensor.py` / `binary_sensor.py`, or add a platform that filters on `device.protocol` like `climate.py`.
- Sending commands (switches, thermostats): encode in `culpy/`, send through the hub. FHT has its own send queue because culfw buffers FHT commands. Most other protocols send immediately but count against the 1 % duty cycle (`X` credit), so keep commands rare.
- Add Home Assistant tests in `tests/ha/` with `FakeTransport` (see `tests/ha/helpers.py`).

### 4. Document

Add the device to the list of supported devices at the top of the README, with pairing steps if it needs any.

## Pull requests

- One topic per pull request, with tests for the change.
- `ruff check` and `pytest` must pass; CI also runs hassfest and the HACS check.
- `main` keeps a linear history: pull requests are squash- or rebase-merged.
- Use clear commit messages, e.g. `fix: …`, `feat: …`, `docs: …`.

By contributing you agree that your contribution is licensed under GPL-3.0.
