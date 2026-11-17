"""Run the bot: ``python -m taskbot``."""

from __future__ import annotations

import logging
import os
import sys

from .config import ConfigError, Settings


def _load_dotenv(path: str = ".env") -> None:
    """Read KEY=value lines from a local .env without overriding the real environment."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    _load_dotenv()
    logging.basicConfig(
        level=os.environ.get("TASKBOT_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        settings = Settings.from_env()
        settings.validate()
    except ConfigError as exc:
        print(f"Config problem: {exc}", file=sys.stderr)
        return 2

    from .bot import TaskBot
    from .store import SheetStore, open_spreadsheet

    store = SheetStore(open_spreadsheet(settings), settings)
    table = store.load_tasks()  # fail fast if the sheet can't be read
    logging.getLogger("taskbot").info(
        "Read %d tasks from the plan (header row %d)", len(table.tasks), table.header_row
    )
    TaskBot(settings, store).run(settings.discord_token, log_handler=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
