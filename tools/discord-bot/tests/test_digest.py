from datetime import date

from taskbot.digest import focus, priorities, recap
from taskbot.planner import WeeklyPlan
from taskbot.sheet import Milestone, Task, Week

DONE = ("done",)
CLOSED = ("cancelled",)
W1 = Week(1, date(2026, 11, 14), date(2026, 11, 20), "Get started")
W2 = Week(2, date(2026, 11, 21), date(2026, 11, 27), "Sensor decision; start the maths")


def task(i, status="Not started", finish=None, signed="", priority="High", week=2):
    return Task(
        row=i + 4,
        id=f"X{i:02d}",
        title=f"Task {i}",
        week=week,
        week_end=week,
        assignees=["Ana"],
        status=status,
        finish=finish,
        signed_off_at=signed,
        priority=priority,
    )


def test_recap_counts_last_weeks_sign_offs_slips_and_blocks():
    tasks = [
        task(1, "Done", date(2026, 11, 18), signed="19 Nov 2026"),
        task(2, "Done", date(2026, 11, 10), signed="2026-11-10"),  # an earlier week
        task(3, "In progress", date(2026, 11, 20)),  # slipped
        task(4, "Blocked", date(2026, 12, 2)),
        task(5, "Cancelled", date(2026, 11, 19)),  # cancelled isn't a slip
    ]
    lines = recap(tasks, W1, DONE, CLOSED)
    assert lines[0] == "### 📈 Week 1 in brief"
    assert lines[1] == "1 task signed off, 1 due that week is still open, 1 in progress, 1 blocked."
    assert lines[2] == "✅ `X01` Task 1"
    assert lines[3] == "⏭️ Carried over: `X03`"
    assert lines[4] == "🚧 Blocked: `X04` Task 4"


def test_recap_says_plainly_when_nothing_was_signed_off():
    assert recap([task(1)], W1, DONE, CLOSED)[1] == "No tasks were signed off."
    assert recap([task(1)], None, DONE, CLOSED) == []


def test_recap_shortens_long_lists():
    tasks = [task(i, "Done", signed="2026-11-15") for i in range(1, 9)]
    assert recap(tasks, W1, DONE, CLOSED)[2].endswith("and 3 more")


def test_priorities_put_overdue_then_critical_then_earliest_first():
    late = task(1, finish=date(2026, 11, 19), week=1)
    crit = task(2, finish=date(2026, 11, 27), priority="Critical")
    soon = task(3, finish=date(2026, 11, 23))
    later = task(4, finish=date(2026, 11, 26))
    plan = WeeklyPlan(week=2, this_week=[later, soon, crit], carried_over=[late])
    assert [t.id for t in priorities(plan)] == ["X01", "X02", "X03", "X04"]


def test_focus_names_the_plan_focus_top_tasks_and_next_gate():
    late = task(1, finish=date(2026, 11, 19), week=1)
    crit = task(2, finish=date(2026, 11, 27), priority="Critical")
    future = task(9, finish=date(2026, 12, 1), week=3)
    plan = WeeklyPlan(week=2, this_week=[crit], carried_over=[late])
    gates = [
        Milestone("M0", date(2026, 11, 14), "Kick-off", "Done"),
        Milestone("M1", date(2026, 11, 20), "Sensors chosen", "Not started"),
        Milestone("M2", date(2026, 12, 1), "Maths done", "Not started"),
    ]
    lines = focus(plan, W2, gates, date(2026, 11, 21), lambda t: "Ana", [late, crit, future])
    assert lines == [
        "### 🎯 Focus for week 2",
        "Sensor decision; start the maths",
        "1. `X01` Task 1 (overdue) · Ana",
        "2. `X02` Task 2 (by 27 Nov, **critical**) · Ana",
        "⚠️ **M1** was due 20 Nov and isn't marked done: Sensors chosen",
        "🏁 **M2** in 10 days (01 Dec): Maths done. 3 open tasks due by then.",
    ]


def test_focus_with_nothing_open_and_no_gates():
    plan = WeeklyPlan(week=5)
    assert focus(plan, None, [], date(2026, 12, 12), lambda t: "") == ["### 🎯 Focus for week 5"]
