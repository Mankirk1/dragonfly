# Dragonfly

[![CI](https://github.com/Mankirk1/dragonfly/actions/workflows/ci.yml/badge.svg)](https://github.com/Mankirk1/dragonfly/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Dragonfly is an open-source Doppler radar tracking system. It aims to turn raw Doppler returns into tracked targets with position, velocity and history.

> **Status:** early development. There is no stable release yet, and APIs will change.

## Goals

- Ingest Doppler radar returns from supported hardware or recorded files
- Estimate target range and radial velocity
- Detect, associate and track targets over time
- Expose tracks through a simple API and visualisation

## Getting started

Requires Python 3.11 or newer.

```bash
git clone https://github.com/Mankirk1/dragonfly.git
cd dragonfly
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pre-commit install               # runs the secret scanner and linters on every commit
cp .env.example .env             # then fill in your own local values
pytest
```

## Tools

| Command | What it does |
|---|---|
| `dragonfly-log --port /dev/ttyUSB0 --out data/t1/session01` | Records RD-03D output to a raw `.bin` file and a decoded `.csv` file. Needs `pip install -e ".[hardware]"`. |
| `dragonfly-log --replay data/t1/session01.bin --out data/t1/redo` | Decodes a saved raw recording again. |
| `dragonfly-sim --scenario S1 --out data/sim/s1` | Simulates an RD-03D session (scenarios S1 to S6) with ground truth, for testing without hardware. |

The simulator's noise and detection settings are starting guesses from the datasheet. They are calibrated once real recordings exist, and simulated results are never a substitute for measured ones.

## Configuration

All configuration comes from environment variables. See [`.env.example`](.env.example) for the full list. Never commit a real `.env` file, credentials, station addresses or recorded data from real sites.

## Project layout

```
src/dragonfly/   Python reference algorithms, simulator and tools
firmware/        ESP32 firmware and its portable C++ core (see firmware/README.md)
tests/           automated tests
docs/            design notes and documentation
.github/         CI, templates and repository automation
```

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) and our [Code of Conduct](CODE_OF_CONDUCT.md) first.

## Security

Please don't report security problems in public issues. See [SECURITY.md](SECURITY.md).

## License

Licensed under the [Apache License 2.0](LICENSE).
