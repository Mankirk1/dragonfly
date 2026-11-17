"""Bot settings, read from ``TASKBOT_*`` environment variables.

Secrets (the Discord token and the Google service account key) only ever come from
the environment or from a git-ignored file. See ``.env.example``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date, time

PREFIX = "TASKBOT_"

DEFAULT_DONE_VALUES = (
    "done",
    "complete",
    "completed",
    "finished",
    "signed off",
    "yes",
    "y",
    "true",
    "x",
    "✅",
    "✔",
    "✓",
)

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class ConfigError(ValueError):
    """Raised when a required setting is missing or malformed."""


DEFAULT_STATUS_VALUES = ("Not started", "In progress", "Blocked", "Postponed", "Done", "Cancelled")
CLOSED_VALUES = ("cancelled", "canceled", "dropped")


@dataclass(frozen=True)
class Columns:
    """Header names in the task tab. Empty means "detect it from common names"."""

    id: str = ""
    week: str = ""
    start: str = ""
    finish: str = ""
    task: str = ""
    assignee: str = ""
    status: str = ""
    due: str = ""
    signed_off_by: str = ""
    signed_off_at: str = ""
    last_updated: str = ""
    progress: str = ""


@dataclass(frozen=True)
class Settings:
    discord_token: str = field(default="", repr=False)
    google_credentials_file: str = ""
    google_credentials_json: str = field(default="", repr=False)
    sheet_id: str = ""
    tasks_tab: str = ""  # empty: the first tab that looks like a task list
    team_tab: str = "TEAM"
    log_tab: str = "WORK LOG"
    checkin_tab: str = "WEEKLY CHECK-IN"
    milestones_tab: str = "MILESTONES"
    header_row: int = 0  # 0: detect it
    day_first: bool = True  # 03/04/2027 is 3 April
    guild_id: int = 0
    channel_id: int = 0
    project_start: date | None = None
    timezone: str = "Europe/Paris"
    weekly_day: int = 0  # Monday
    weekly_time: time = time(9, 0)
    reminder_day: int | None = 3  # Thursday; None turns reminders off
    done_values: tuple[str, ...] = DEFAULT_DONE_VALUES
    done_label: str = "Done"
    reopen_label: str = "In progress"
    status_values: tuple[str, ...] = DEFAULT_STATUS_VALUES
    closed_values: tuple[str, ...] = CLOSED_VALUES
    auto_add_columns: bool = True
    columns: Columns = Columns()

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        env = dict(os.environ) if env is None else env

        def get(name: str, default: str = "") -> str:
            return env.get(PREFIX + name, default).strip()

        def get_int(name: str, default: int = 0) -> int:
            raw = get(name)
            if not raw:
                return default
            try:
                return int(raw)
            except ValueError as exc:
                raise ConfigError(f"{PREFIX}{name} must be a whole number") from exc

        start = get("PROJECT_START")
        try:
            project_start = date.fromisoformat(start) if start else None
        except ValueError as exc:
            raise ConfigError(f"{PREFIX}PROJECT_START must look like 2026-09-07") from exc

        done_raw = get("DONE_VALUES")
        done_values = (
            tuple(v.strip().casefold() for v in done_raw.split(",") if v.strip())
            if done_raw
            else DEFAULT_DONE_VALUES
        )

        done_label = get("DONE_LABEL", "Done")
        # A finished task always counts as done, and so does a ticked checkbox.
        done_values = tuple(dict.fromkeys((*done_values, done_label.casefold(), "true")))

        reminder = get("REMINDER_DAY", "thu")
        return cls(
            discord_token=get("DISCORD_TOKEN"),
            google_credentials_file=get("GOOGLE_CREDENTIALS_FILE"),
            google_credentials_json=get("GOOGLE_CREDENTIALS_JSON"),
            sheet_id=_sheet_id(get("SHEET_ID")),
            tasks_tab=get("TASKS_TAB"),
            team_tab=get("TEAM_TAB", "TEAM"),
            log_tab=get("LOG_TAB", "WORK LOG"),
            checkin_tab=get("CHECKIN_TAB", "WEEKLY CHECK-IN"),
            milestones_tab=get("MILESTONES_TAB", "MILESTONES"),
            header_row=get_int("HEADER_ROW"),
            day_first=get("DATE_ORDER", "dmy").lower() != "mdy",
            guild_id=get_int("GUILD_ID"),
            channel_id=get_int("CHANNEL_ID"),
            project_start=project_start,
            timezone=get("TIMEZONE", "Europe/Paris"),
            weekly_day=_weekday(get("WEEKLY_DAY", "mon"), "WEEKLY_DAY"),
            weekly_time=_clock(get("WEEKLY_TIME", "09:00")),
            reminder_day=None
            if reminder.lower() in ("", "off", "none")
            else _weekday(reminder, "REMINDER_DAY"),
            done_values=done_values,
            done_label=done_label,
            reopen_label=get("REOPEN_LABEL", "In progress"),
            status_values=tuple(v.strip() for v in get("STATUS_VALUES").split(",") if v.strip())
            or DEFAULT_STATUS_VALUES,
            auto_add_columns=get("AUTO_ADD_COLUMNS", "true").lower() in ("1", "true", "yes"),
            columns=Columns(
                id=get("COL_ID"),
                week=get("COL_WEEK"),
                start=get("COL_START"),
                finish=get("COL_FINISH"),
                task=get("COL_TASK"),
                assignee=get("COL_ASSIGNEE"),
                status=get("COL_STATUS"),
                due=get("COL_DUE"),
                signed_off_by=get("COL_SIGNED_OFF_BY"),
                signed_off_at=get("COL_SIGNED_OFF_AT"),
                last_updated=get("COL_LAST_UPDATED"),
                progress=get("COL_PROGRESS"),
            ),
        )

    def validate(self) -> None:
        """Check the settings the running bot can't do without."""
        missing = [
            name
            for name, value in (
                ("DISCORD_TOKEN", self.discord_token),
                ("SHEET_ID", self.sheet_id),
                ("CHANNEL_ID", self.channel_id),
            )
            if not value
        ]
        if not (self.google_credentials_file or self.google_credentials_json):
            missing.append("GOOGLE_CREDENTIALS_FILE or GOOGLE_CREDENTIALS_JSON")
        if missing:
            raise ConfigError("Missing settings: " + ", ".join(PREFIX + m for m in missing))

    def google_credentials(self) -> dict:
        """The service account key as a dict."""
        if self.google_credentials_json:
            return json.loads(self.google_credentials_json)
        with open(self.google_credentials_file, encoding="utf-8") as fh:
            return json.load(fh)


def _sheet_id(raw: str) -> str:
    """Accept a bare Sheet ID or a full docs.google.com link."""
    marker = "/spreadsheets/d/"
    if marker in raw:
        return raw.split(marker, 1)[1].split("/", 1)[0].split("?", 1)[0]
    return raw


def _weekday(raw: str, name: str) -> int:
    key = raw.strip().lower()[:3]
    if key not in WEEKDAYS:
        raise ConfigError(f"{PREFIX}{name} must be a day such as mon or thu")
    return WEEKDAYS.index(key)


def _clock(raw: str) -> time:
    try:
        hour, minute = raw.split(":")
        return time(int(hour), int(minute))
    except ValueError as exc:
        raise ConfigError(f"{PREFIX}WEEKLY_TIME must look like 09:00") from exc
