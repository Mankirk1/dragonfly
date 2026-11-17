"""The layout of the team's real plan, with made-up names and tasks.

TASK BOARD with title rows, target start/finish dates and "A + All" owners; a WORK LOG
to append to; a WEEKLY CHECK-IN that defines the weeks; and MILESTONES.
"""

from datetime import date

from taskbot.config import Settings
from taskbot.planner import build_plan
from taskbot.sheet import people_for
from taskbot.store import SheetStore

from .fakes import FakeBook, FakeWorksheet

HEADERS = [
    "ID", "Workstream", "Planned task (editable)", "Owner(s)", "Target start", "Target finish",
    "Expected output", "Depends on", "Priority", "Status", "What changed / actual progress",
    "Next action / rescheduled work", "Last updated", "Notes / links", "Completion date",
]  # fmt: skip


def task(i, owners, start, finish, status="Not started", priority="High"):
    row = [""] * len(HEADERS)
    row[0], row[2], row[3], row[4], row[5] = f"X{i:02d}", f"Task {i}", owners, start, finish
    row[8], row[9] = priority, status
    return row


def book():
    intro = FakeWorksheet("START HERE", [["HUB"], ["How to use"], ["Completed", "=COUNTIF()"]])
    board = FakeWorksheet(
        "TASK BOARD",
        [
            ["TASK BOARD | THE LIVING PLAN"] + [""] * 14,
            ["Edit freely"] + [""] * 14,
            [""] * 15,
            HEADERS,
            task(1, "Ana + Ben", "2026-10-28", "2026-11-13", "Done"),
            task(2, "All", "14/11/2026", "20/11/2026", priority="Critical"),
            task(3, "Cy + All", "2026-11-16", "2026-11-27"),
            task(4, "Ben", "2026-11-01", "2026-11-12", "In progress"),
            task(5, "Ana", "2026-11-28", "2026-12-04"),
            task(6, "Ben", "2026-11-14", "2026-11-20", "Cancelled"),
        ],
    )
    log = FakeWorksheet(
        "WORK LOG",
        [
            ["WORK LOG"] + [""] * 10,
            ["Never overwrite"] + [""] * 10,
            [""] * 11,
            [
                "Date",
                "Week beginning",
                "Member",
                "Related task ID",
                "Planned for this session",
                "What was actually done",
                "Outcome / evidence link",
                "Status / result",
                "Carryover / new target",
                "Next action",
                "Blocker / comments",
            ],  # fmt: skip
            ["2026-11-14", "2026-11-09", "Ana", "X01", "x", "y", "", "Done", "", "", ""],
        ],
    )
    checkin = FakeWorksheet(
        "WEEKLY CHECK-IN",
        [
            ["WEEKLY CHECK-IN"] + [""] * 9,
            ["Each week is editable"] + [""] * 9,
            [""] * 10,
            [
                "Week",
                "Week starts",
                "Week ends",
                "Suggested focus (editable)",
                "Agreed team priorities",
                "What we actually completed",
                "Work moved / new week",
                "Decisions / blockers",
                "Update owner",
                "Meeting / update date",
            ],  # fmt: skip
            ["W01", "2026-11-14", "2026-11-20", "Pick sensors"] + [""] * 6,
            ["W02", "2026-11-21", "2026-11-27", "Maths"] + [""] * 6,
        ],
    )
    milestones = FakeWorksheet(
        "MILESTONES",
        [
            ["MILESTONES"],
            ["Update targets"],
            [""],
            ["Gate", "Target date", "Milestone / acceptance criteria", "Owner(s)", "Status"],
            ["M0", "2026-11-14", "Kick-off", "All", "Done"],
            ["M1", "2026-11-27", "Sensors chosen", "All", "Not started"],
        ],
    )
    return FakeBook(intro, board, log, checkin, milestones)


def setup():
    b = book()
    store = SheetStore(b, Settings())
    cal = store.load_calendar()
    return b, store, cal


def test_reads_weeks_and_milestones_from_their_tabs():
    _, _, cal = setup()
    assert cal.start == date(2026, 11, 14)
    assert cal.week(2).focus == "Maths"
    assert [m.gate for m in cal.milestones] == ["M0", "M1"]


def test_finds_the_task_board_and_leaves_it_untouched():
    b, store, cal = setup()
    before = [list(r) for r in b.sheets[1].rows]
    table = store.load_tasks(cal.start)
    assert b.sheets[1].rows == before
    assert table.header_row == 4
    t2 = table.find("x02")
    assert (t2.week, t2.week_end, t2.due, t2.priority) == (1, 1, "20 Nov", "Critical")
    assert table.find("X03").assignees == ["Cy", "All"]
    assert (table.find("X03").week, table.find("X03").week_end) == (1, 2)


def test_plan_expands_all_and_skips_cancelled():
    b, store, cal = setup()
    table = store.load_tasks(cal.start)
    team = store.load_team([n for t in table.tasks for n in t.assignees])
    assert [m.name for m in team] == ["Ana", "Ben", "Cy"]  # "All" isn't a person
    s = Settings()
    plan = build_plan(table.tasks, 1, team, s.done_values, s.closed_values)
    assert [t.id for t in plan.carried_over] == ["X04"]
    assert [t.id for t in plan.this_week] == ["X02", "X03"]
    assert plan.unmatched_names == set()
    assert {k: [t.id for t in v] for k, v in plan.by_member(team).items()} == {
        "Ana": ["X02", "X03"],
        "Ben": ["X04", "X02", "X03"],
        "Cy": ["X02", "X03"],
    }
    assert [m.name for m in people_for(["Cy", "All"], team)] == ["Cy", "Ana", "Ben"]


def test_sign_off_fills_status_dates_and_progress_and_logs_under_history():
    b, store, cal = setup()
    table = store.load_tasks(cal.start)
    store.update_task(
        "X02",
        {
            "status": "Done",
            "signed_off_at": "2026-11-17",
            "last_updated": "2026-11-17",
            "progress": "Chose sensor",
        },
    )
    store.update_task("X02", {"progress": "Ordered"})
    row = b.sheets[1].rows[5]
    assert row[9] == "Done"
    assert row[10] == "Chose sensor; Ordered"
    assert row[12] == "2026-11-17" and row[14] == "2026-11-17"
    store.log(date(2026, 11, 17), cal.start, table.find("X02"), "Signed off in Discord", "Ana",
              "Done")  # fmt: skip
    log = b.sheets[2].rows
    assert len(log) == 6 and log[4][3] == "X01"  # old entry kept
    assert log[5][:8] == [
        "2026-11-17", "2026-11-14", "Ana", "X02", "Task 2", "Signed off in Discord", "", "Done",
    ]  # fmt: skip


def test_check_in_is_filled_only_where_blank():
    b, store, _ = setup()
    assert store.fill_checkin(1, "Done: X02", "Still open: X03")
    store.fill_checkin(1, "Done: other", "")
    row = b.sheets[3].rows[4]
    assert row[5] == "Done: X02" and row[6] == "Still open: X03"


def test_new_ids_follow_the_existing_pattern():
    from taskbot.sheet import Task, next_ids

    tasks = [Task(5, "R09", "a", 1, 1), Task(6, "", "b", 1, 1), Task(7, "R10", "c", 1, 1)]
    assert next_ids(tasks) == {6: "R11"}
