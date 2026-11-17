"""Decide who does what this week, from what's done and what's left."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .sheet import Member, Task, is_everyone, match_member, people_for


def current_week(today: date, project_start: date | None, tasks: list[Task]) -> int:
    """The project week that ``today`` falls in.

    With a start date it's counted from that day. Without one, it's the earliest week
    that still has open work, so the bot keeps pushing the oldest work first.
    """
    if project_start is not None:
        return max(1, (today - project_start).days // 7 + 1)
    weeks = [t.week for t in tasks if t.week is not None]
    return min(weeks) if weeks else 1


@dataclass
class WeeklyPlan:
    week: int
    this_week: list[Task] = field(default_factory=list)  # open, scheduled for this week
    carried_over: list[Task] = field(default_factory=list)  # open, should have finished
    done_last_week: list[Task] = field(default_factory=list)
    new_assignments: dict[str, list[str]] = field(default_factory=dict)  # task id -> names
    unmatched_names: set[str] = field(default_factory=set)

    @property
    def open_tasks(self) -> list[Task]:
        return self.carried_over + self.this_week

    def by_member(self, team: list[Member]) -> dict[str, list[Task]]:
        """Each member's open tasks, with "All" tasks given to everyone."""
        out: dict[str, list[Task]] = {}
        for t in self.open_tasks:
            for m in people_for(t.assignees, team):
                out.setdefault(m.name, []).append(t)
        return out


def build_plan(
    tasks: list[Task],
    week: int,
    team: list[Member],
    done_values: tuple[str, ...],
    closed_values: tuple[str, ...] = (),
    auto_assign: bool = True,
) -> WeeklyPlan:
    """Sort open work into this week and carried over, and share out unassigned tasks.

    Unassigned tasks go to whoever has the fewest open tasks; ties rotate each week so
    the same person doesn't always get the first pick.
    """
    plan = WeeklyPlan(week=week)
    for t in tasks:
        if t.is_done(done_values):
            if t.week is not None and (t.week_end or t.week) == week - 1:
                plan.done_last_week.append(t)
            continue
        if t.is_closed(closed_values):
            continue
        if t.overdue_in(week):
            plan.carried_over.append(t)
        elif t.active_in(week):
            plan.this_week.append(t)

    for t in plan.open_tasks:
        for name in t.assignees:
            if not is_everyone(name) and match_member(name, team) is None:
                plan.unmatched_names.add(name)

    if not auto_assign or not team:
        return plan

    load = {m.name: 0 for m in team}
    for t in plan.open_tasks:
        for m in people_for(t.assignees, team):
            load[m.name] += 1

    order = [m.name for m in team]
    shift = week % len(order)
    order = order[shift:] + order[:shift]
    for t in plan.open_tasks:  # carried-over work is placed first
        if t.assignees:
            continue
        pick = min(order, key=lambda n: (load[n], order.index(n)))
        load[pick] += 1
        t.assignees = [pick]
        plan.new_assignments[t.id] = [pick]
    return plan
