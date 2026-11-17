from datetime import date, time

import pytest
from taskbot.config import ConfigError, Settings


def test_from_env_reads_everything():
    s = Settings.from_env(
        {
            "TASKBOT_SHEET_ID": "https://docs.google.com/spreadsheets/d/abc123/edit#gid=0",
            "TASKBOT_PROJECT_START": "2026-09-07",
            "TASKBOT_WEEKLY_DAY": "Tuesday",
            "TASKBOT_WEEKLY_TIME": "08:30",
            "TASKBOT_REMINDER_DAY": "off",
            "TASKBOT_CHANNEL_ID": "99",
            "TASKBOT_COL_TASK": "Deliverable",
            "TASKBOT_DONE_VALUES": "Fini, OK",
        }
    )
    assert s.sheet_id == "abc123"
    assert s.project_start == date(2026, 9, 7)
    assert s.weekly_day == 1 and s.weekly_time == time(8, 30)
    assert s.reminder_day is None
    assert s.channel_id == 99
    assert s.columns.task == "Deliverable"
    assert s.done_values == ("fini", "ok", "done", "true")


def test_validate_lists_missing_secrets():
    with pytest.raises(ConfigError, match="DISCORD_TOKEN"):
        Settings.from_env({}).validate()


def test_bad_values_are_explained():
    with pytest.raises(ConfigError):
        Settings.from_env({"TASKBOT_WEEKLY_DAY": "someday"})
    with pytest.raises(ConfigError):
        Settings.from_env({"TASKBOT_PROJECT_START": "next monday"})


def test_token_is_not_in_repr():
    assert "tok-not-shown" not in repr(Settings(discord_token="tok-not-shown"))
