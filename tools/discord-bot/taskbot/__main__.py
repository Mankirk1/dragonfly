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
    if os.name == "posix" and os.stat(path).st_mode & 0o027:
        # Group may read (root:taskbot 640) but nobody else may read, and only the owner
        # may change it, so settings can't be swapped by another account on the machine.
        logging.getLogger("taskbot").warning(
            "%s can be read or changed by other users on this machine. Run: chmod 640 %s",
            path,
            path,
        )
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("TASKBOT_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _load_dotenv()
    try:
        settings = Settings.from_env()
        settings.validate()
    except ConfigError as exc:
        print(f"Config problem: {exc}", file=sys.stderr)
        return 2

    from .bot import TaskBot
    from .gcp import read_secret
    from .store import SheetStore, open_spreadsheet

    try:
        token = settings.discord_token or read_secret(settings.discord_token_secret)
    except ConfigError as exc:
        print(f"Config problem: {exc}", file=sys.stderr)
        return 2
    store = SheetStore(open_spreadsheet(settings), settings)
    table = store.load_tasks()  # fail fast if the sheet can't be read
    logging.getLogger("taskbot").info(
        "Read %d tasks from the plan (header row %d)", len(table.tasks), table.header_row
    )
    TaskBot(settings, store).run(token, log_handler=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
