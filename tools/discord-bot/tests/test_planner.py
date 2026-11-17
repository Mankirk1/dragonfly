from datetime import date

from taskbot.planner import build_plan, current_week
from taskbot.sheet import Member, Task

DONE = ("done",)


def task(tid, week, assignees=(), status="", week_end=None):
    return Task(
        row=1,
        id=tid,
        title=tid,
        week=week,
        week_end=week_end,
        assignees=list(assignees),
        status=status,
    )


TEAM = [Member(2, "Ana", 1), Member(3, "Ben", 2), Member(4, "Dana", 3)]


def test_current_week_from_start_date():
    assert current_week(date(2026, 9, 7), date(2026, 9, 7), []) == 1
    assert current_week(date(2026, 9, 20), date(2026, 9, 7), []) == 2
    assert current_week(date(2026, 8, 1), date(2026, 9, 7), []) == 1


def test_current_week_without_start_is_oldest_open_week():
    assert current_week(date(2026, 1, 1), None, [task("a", 3), task("b", 2)]) == 2


def test_plan_sorts_done_carried_and_this_week():
    tasks = [
        task("old-done", 1, ["Ana"], "Done"),
        task("last-done", 2, ["Ben"], "Done"),
        task("late", 2, ["Ben"]),
        task("now", 3, ["Dana"]),
        task("span", 2, ["Ana"], week_end=4),
        task("later", 4, ["Ana"]),
    ]
    plan = build_plan(tasks, 3, TEAM, DONE)
    assert [t.id for t in plan.carried_over] == ["late"]
    assert [t.id for t in plan.this_week] == ["now", "span"]
    assert [t.id for t in plan.done_last_week] == ["last-done"]
    assert plan.new_assignments == {}


def test_unassigned_work_goes_to_the_least_loaded():
    tasks = [
        task("a1", 1, ["Ana"]),
        task("a2", 1, ["Ana"]),
        task("b1", 1, ["Ben"]),
        task("x", 1),
        task("y", 1),
    ]
    plan = build_plan(tasks, 1, TEAM, DONE)
    assert plan.new_assignments["x"] == ["Dana"]
    assert plan.new_assignments["y"] in (["Ben"], ["Dana"])
    counts = {}
    for t in plan.open_tasks:
        counts[t.assignees[0]] = counts.get(t.assignees[0], 0) + 1
    assert max(counts.values()) - min(counts.values()) <= 1


def test_carried_over_is_assigned_before_new_work():
    tasks = [task("new", 2), task("old", 1)]
    plan = build_plan(tasks, 2, [Member(2, "Ana", 1)], DONE)
    assert [t.id for t in plan.open_tasks] == ["old", "new"]


def test_unknown_names_are_reported_not_reassigned():
    plan = build_plan([task("a", 1, ["Zed"])], 1, TEAM, DONE)
    assert plan.unmatched_names == {"Zed"}
    assert plan.new_assignments == {}


def test_no_auto_assign():
    plan = build_plan([task("a", 1)], 1, TEAM, DONE, auto_assign=False)
    assert plan.new_assignments == {} and plan.this_week[0].assignees == []
