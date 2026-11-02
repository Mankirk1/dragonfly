"""Runtime configuration, read from environment variables.

Secrets and site details never live in code. Set them in your environment or
in a local, git-ignored ``.env`` file. See ``.env.example`` for the variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_PREFIX = "DRAGONFLY_"


@dataclass(frozen=True)
class Settings:
    radar_host: str = "127.0.0.1"
    radar_port: int = 5000
    api_key: str = field(default="", repr=False)  # never shown in logs or reprs
    data_dir: Path = Path("./data")
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        """Build settings from ``env`` (defaults to ``os.environ``)."""
        env = dict(os.environ) if env is None else env

        def get(name: str, default: str) -> str:
            return env.get(_PREFIX + name, default)

        return cls(
            radar_host=get("RADAR_HOST", cls.radar_host),
            radar_port=int(get("RADAR_PORT", str(cls.radar_port))),
            api_key=get("API_KEY", ""),
            data_dir=Path(get("DATA_DIR", str(cls.data_dir))),
            log_level=get("LOG_LEVEL", cls.log_level).upper(),
        )
