"""The bot's sign-off, permission and undo rules, run against the fake Sheet.

Discord itself isn't contacted: announcements and the admin check are stubbed.
"""

import asyncio
import time
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
import taskbot.bot as bot_module
from taskbot.bot import HELP_TEXT, TaskBot, task_details
from taskbot.config import Settings
from taskbot.digest import gate_heads_up
from taskbot.sheet import Milestone, Task
from taskbot.store import SheetStore

from .test_layout import book

ANA, BEN, CY, STRANGER = 1001, 1002, 1003, 1999

# The bot's today() is faked to 21 Nov below. The Undo button stamps the wall-clock time
# and undo works out the sign-off date from it, so the wall clock must say 21 Nov too,
# or the undo tests only pass when they happen to run on 21 Nov.
SIGN_OFF_AT = int(datetime(2026, 11, 21, 12, 0, tzinfo=ZoneInfo("Europe/Paris")).timestamp())


class FrozenClock:
    """Stands in for the `time` module inside taskbot.bot."""

    monotonic = staticmethod(time.monotonic)

    @staticmethod
    def time():
        return float(SIGN_OFF_AT)


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    monkeypatch.setattr(bot_module, "clock", FrozenClock)


@dataclass
class User:
    id: int
    display_name: str = "someone"


def make_bot(admins=()):
    b = book()
    store = SheetStore(b, Settings())
    store.load_team(["Ana", "Ben", "Cy"])
    for name, uid in (("Ana", ANA), ("Ben", BEN), ("Cy", CY)):
        store.link_member(name, uid)
    bot = TaskBot(Settings(channel_id=1), store)
    bot.posts = []

    async def announce(text):
        bot.posts.append(text)

    async def is_admin(user):
        return user.id in admins

    bot.announce = announce
    bot.is_admin = is_admin
    bot.today = lambda: date(2026, 11, 21)
    return bot, b


def board(b):
    return b.sheets[1]


def work_log(b):
    return b.sheets[2]


def row_of(b, task_id):
    return next(r for r in board(b).rows if r and r[0] == task_id)


def run(coro):
    return asyncio.run(coro)


def test_owner_signs_off_with_what_was_done_and_evidence():
    bot, b = make_bot()
    message, undo = run(
        bot.sign_off("X05", User(ANA, "Ana"), "Wired it up", "https://example.com/photo")
    )
    assert message.startswith("✅") and undo is not None
    row = row_of(b, "X05")
    assert row[9] == "Done" and row[14] == "2026-11-21" and row[12] == "2026-11-21"
    assert "Wired it up https://example.com/photo (Ana, 21 Nov)" in row[10]
    last = work_log(b).rows[-1]
    assert last[2:8] == [
        "Ana",
        "X05",
        "Task 5",
        "Wired it up (signed off in Discord)",
        "https://example.com/photo",
        "Done",
    ]
    assert "🔗 <https://example.com/photo>" in bot.posts[-1]


def test_someone_else_cant_sign_off_your_task():
    bot, b = make_bot()
    before = [list(r) for r in board(b).rows]
    message, undo = run(bot.sign_off("X05", User(BEN, "Ben")))
    assert message.startswith("⛔") and "belongs to Ana" in message and undo is None
    assert board(b).rows == before and bot.posts == []


def test_unlinked_people_are_told_to_link_first():
    bot, _ = make_bot()
    message, _ = run(bot.sign_off("X02", User(STRANGER)))
    assert "/link" in message


def test_all_tasks_and_admins():
    bot, b = make_bot(admins={STRANGER})
    assert run(bot.sign_off("X02", User(BEN)))[0].startswith("✅")  # owned by "All"
    assert run(bot.sign_off("X03", User(ANA)))[0].startswith("✅")  # "Cy + All"
    assert run(bot.sign_off("X05", User(STRANGER)))[0].startswith("✅")  # an admin


def test_status_changes_and_assign_follow_the_same_rule():
    bot, b = make_bot()
    message, _ = run(bot.change_status("X05", User(BEN), "Blocked", "waiting"))
    assert message.startswith("⛔") and row_of(b, "X05")[9] == "Not started"
    message, _ = run(bot.change_status("X05", User(ANA), "Blocked", "waiting"))
    assert row_of(b, "X05")[9] == "Blocked"
    assert work_log(b).rows[-1][10] == "waiting"  # status notes still go to comments
    assert run(bot.assign("X05", User(CY), User(BEN))).startswith("⛔")
    assert row_of(b, "X05")[3] == "Ana"


def test_undo_puts_everything_back_and_logs_it():
    bot, b = make_bot()
    before = list(row_of(b, "X05"))
    run(bot.sign_off("X05", User(ANA, "Ana")))
    at = int(datetime(2026, 11, 21, 12, 0, tzinfo=bot.tz).timestamp())
    message = run(bot.undo_sign_off("X05", User(ANA, "Ana"), 0, at))
    assert message.startswith("↩️") and "Not started" in message
    row = row_of(b, "X05")
    assert row[9] == "Not started" and row[14] == ""
    assert [c for i, c in enumerate(row) if i not in (12,)] == [
        c for i, c in enumerate(before) if i not in (12,)
    ]  # only Last updated differs from before the sign-off
    assert work_log(b).rows[-1][5] == "Sign-off undone in Discord (back to Not started)"


def undo_now(bot, task_id, user, signed_with):
    """Press the Undo button that came with a sign-off."""
    button = signed_with.children[0]
    return run(bot.undo_sign_off(task_id, user, button.prev, button.at, button.note))


def test_undo_takes_back_the_sign_off_note():
    bot, b = make_bot()
    row_of(b, "X05")[10] = ""
    _, undo = run(bot.sign_off("X05", User(ANA), "Wired it up", "https://example.com/p"))
    assert row_of(b, "X05")[10] == "Wired it up https://example.com/p (Ana, 21 Nov)"
    assert undo_now(bot, "X05", User(ANA), undo).startswith("↩️")
    assert row_of(b, "X05")[10] == "" and row_of(b, "X05")[9] == "Not started"


def test_undo_keeps_the_notes_that_were_there_before():
    bot, b = make_bot()
    row_of(b, "X05")[10] = "Parts ordered (Ben, 18 Nov)"
    _, undo = run(bot.sign_off("X05", User(ANA), "Wired it up"))
    assert row_of(b, "X05")[10] == "Parts ordered (Ben, 18 Nov); Wired it up (Ana, 21 Nov)"
    undo_now(bot, "X05", User(ANA), undo)
    assert row_of(b, "X05")[10] == "Parts ordered (Ben, 18 Nov)"


def test_undo_leaves_a_note_someone_changed_by_hand():
    bot, b = make_bot()
    row_of(b, "X05")[10] = ""
    _, undo = run(bot.sign_off("X05", User(ANA), "Wired it up"))
    row_of(b, "X05")[10] = "Wired it up, then tested it (Ana, 21 Nov)"  # edited in the Sheet
    undo_now(bot, "X05", User(ANA), undo)
    assert row_of(b, "X05")[10] == "Wired it up, then tested it (Ana, 21 Nov)"
    row_of(b, "X05")[10] = ""
    _, undo = run(bot.sign_off("X05", User(ANA), "Wired it up"))
    row_of(b, "X05")[10] += "; Checked by Ben"  # someone added a note after it
    undo_now(bot, "X05", User(ANA), undo)
    assert row_of(b, "X05")[10] == "Wired it up (Ana, 21 Nov); Checked by Ben"


def test_undo_never_clears_a_date_someone_else_typed():
    bot, b = make_bot()
    run(bot.sign_off("X05", User(ANA)))
    row_of(b, "X05")[14] = "2026-11-25"  # someone corrects the completion date by hand
    at = SIGN_OFF_AT
    run(bot.undo_sign_off("X05", User(ANA), 0, at))
    assert row_of(b, "X05")[14] == "2026-11-25"


def test_undo_refuses_when_the_task_moved_on():
    bot, b = make_bot()
    run(bot.sign_off("X05", User(ANA)))
    row_of(b, "X05")[9] = "In progress"
    message = run(bot.undo_sign_off("X05", User(ANA), 0, SIGN_OFF_AT))
    assert "nothing to undo" in message and row_of(b, "X05")[9] == "In progress"


def test_task_details_show_expected_output_and_next_action():
    t = Task(1, "R1", "Pick", 1, 1, expected="Sensor chosen", next_action="Ask tutor " * 30)
    lines = task_details(t)
    assert lines[0] == "   ↳ Done means: Sensor chosen"
    assert lines[1].startswith("   ↳ Next: Ask tutor") and lines[1].endswith("…")
    assert task_details(Task(1, "R1", "Pick", 1, 1)) == []


def test_gate_heads_up_two_days_before():
    gates = [
        Milestone("M1", date(2026, 11, 27), "Sensors chosen", "Not started"),
        Milestone("M2", date(2026, 11, 27), "Already done", "Done"),
    ]
    late = Task(1, "R1", "Order", 1, 1, finish=date(2026, 11, 26), priority="High")
    later = Task(2, "R2", "Build", 2, 2, finish=date(2026, 12, 2))
    lines = gate_heads_up(gates, [late, later], date(2026, 11, 25), 2, lambda t: "Ana")
    assert lines == [
        "⏰ **M1** is in 2 days (Fri 27 Nov): Sensors chosen",
        "Still open and due by then (1):",
        "• `R1` Order · Ana",
    ]
    assert gate_heads_up(gates, [], date(2026, 11, 24), 2, lambda t: "") == []
    assert gate_heads_up(gates, [], date(2026, 11, 25), 0, lambda t: "") == []


def test_help_fits_in_one_discord_message():
    assert len(HELP_TEXT) < 2000


@pytest.mark.parametrize("link", ["javascript:alert(1)", "https://a b", "=IMPORTXML(x)"])
def test_bad_evidence_links_are_refused(link):
    from taskbot.sheet import clean_link

    assert clean_link(link) is None


def test_sheet_outage_alerts_once_after_30_minutes_then_says_when_back():
    bot, _ = make_bot()
    alerts = []

    async def alert(text):
        alerts.append(text)
        return True

    def down():
        raise ConnectionError("no route")

    bot.alert = alert
    bot.store.ping = down
    run(bot._health_tick())
    assert alerts == [] and bot._down_since is not None
    bot._down_since -= 31 * 60
    run(bot._health_tick())
    run(bot._health_tick())
    assert len(alerts) == 1 and "30 minutes" in alerts[0]
    bot.store.ping = lambda: None
    run(bot._health_tick())
    assert alerts[-1].startswith("✅") and bot._down_since is None and not bot._alerted


def test_buttons_and_form_build_and_round_trip():
    import re

    from taskbot.bot import DoneButton, SignOffForm, UndoButton, undo_view

    async def build():
        view = undo_view("R06", 123456789012345678, 3, 342)
        button = view.children[0]
        cid = button.custom_id
        assert len(cid) <= 100
        m = re.fullmatch(UndoButton.__discord_ui_compiled_template__, cid)
        assert m and m["id"] == "R06" and m["user"] == "123456789012345678"
        assert m["prev"] == "3" and m["note"] == "342"
        again = await UndoButton.from_custom_id(None, button, m)
        assert (again.task_id, again.user_id, again.prev, again.note) == (
            "R06",
            123456789012345678,
            3,
            342,
        )
        form = SignOffForm("R06")
        assert form.title == "Sign off R06" and len(form.children) == 2
        assert DoneButton("R06", "x").item.custom_id == "taskbot:done:R06"

    run(build())
