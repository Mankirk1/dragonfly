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

## Configuration

All configuration comes from environment variables. See [`.env.example`](.env.example) for the full list. Never commit a real `.env` file, credentials, station addresses or recorded data from real sites.

## Project layout

```
src/dragonfly/   library code
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
