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

## Pull requests

- One topic per pull request, with tests for the change.
- `ruff check` and `pytest` must pass; CI also runs hassfest and the HACS check.
- `main` keeps a linear history: pull requests are squash- or rebase-merged.
- Use clear commit messages, e.g. `fix: …`, `feat: …`, `docs: …`.

By contributing you agree that your contribution is licensed under GPL-3.0.
