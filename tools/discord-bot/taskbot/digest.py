"""The short "last week in brief" and "focus for this week" parts of the weekly post.

Built only from what's in the Sheet (statuses, completion dates, target dates,
priorities, the WEEKLY CHECK-IN focus and the MILESTONES), so it says nothing the
plan doesn't support.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from .planner import WeeklyPlan
from .sheet import Milestone, Task, Week, parse_date

PRIORITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
MAX_NAMED = 5  # list at most this many tasks per line, then "and N more"
TOP_PRIORITIES = 3


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _names(tasks: list[Task], limit: int = MAX_NAMED) -> str:
    named = ", ".join(f"`{t.id}` {t.title}" for t in tasks[:limit])
    rest = len(tasks) - limit
    return f"{named} and {rest} more" if rest > 0 else named


def _status(t: Task) -> str:
    return t.status.strip().casefold()


def recap(
    tasks: list[Task],
    last: Week | None,
    done_values: tuple[str, ...],
    closed_values: tuple[str, ...],
    day_first: bool = True,
) -> list[str]:
    """What happened in the week that just ended: finished, slipped, blocked."""
    if last is None:
        return []

    def open_(t: Task) -> bool:
        return not t.is_done(done_values) and not t.is_closed(closed_values)

    finished = [
        t
        for t in tasks
        if t.is_done(done_values)
        and (d := parse_date(t.signed_off_at, day_first)) is not None
        and last.start <= d <= last.end
    ]
    slipped = [t for t in tasks if open_(t) and t.finish and last.start <= t.finish <= last.end]
    blocked = [t for t in tasks if open_(t) and _status(t) == "blocked"]
    in_progress = [t for t in tasks if open_(t) and _status(t) == "in progress"]

    parts = [
        f"{_plural(len(finished), 'task')} signed off" if finished else "No tasks were signed off"
    ]
    if slipped:
        parts.append(
            f"{len(slipped)} due that week {'is' if len(slipped) == 1 else 'are'} still open"
        )
    if in_progress:
        parts.append(f"{len(in_progress)} in progress")
    if blocked:
        parts.append(f"{len(blocked)} blocked")

    lines = [f"### 📈 Week {last.number} in brief", ", ".join(parts) + "."]
    if finished:
        lines.append(f"✅ {_names(finished)}")
    if slipped:
        lines.append("⏭️ Carried over: " + ", ".join(f"`{t.id}`" for t in slipped))
    if blocked:
        lines.append(f"🚧 Blocked: {_names(blocked)}")
    return lines


def next_gate(milestones: list[Milestone], today: date) -> Milestone | None:
    upcoming = [
        m
        for m in milestones
        if m.target and m.target >= today and m.status.strip().casefold() != "done"
    ]
    return min(upcoming, key=lambda m: m.target or date.max, default=None)


def priorities(plan: WeeklyPlan) -> list[Task]:
    """The open tasks to do first: overdue, then by priority, then by target finish."""
    overdue = {t.id for t in plan.carried_over}
    return sorted(
        plan.open_tasks,
        key=lambda t: (
            t.id not in overdue,
            PRIORITY_RANK.get(t.priority.strip().casefold(), len(PRIORITY_RANK)),
            t.finish or date.max,
        ),
    )


def focus(
    plan: WeeklyPlan,
    week: Week | None,
    milestones: list[Milestone],
    today: date,
    owners: Callable[[Task], str],
    open_tasks: list[Task] | None = None,
) -> list[str]:
    """What to concentrate on this week: the plan's focus, the top tasks, the next gate.

    ``open_tasks`` is every unfinished task in the plan, to count what's due before
    the next gate; it defaults to this week's open tasks.
    """
    lines = [f"### 🎯 Focus for week {plan.week}"]
    if week and week.focus:
        lines.append(week.focus)
    top = priorities(plan)[:TOP_PRIORITIES]
    if top:
        overdue = {t.id for t in plan.carried_over}
        for i, t in enumerate(top, 1):
            extra = []
            if t.id in overdue:
                extra.append("overdue")
            elif t.finish:
                extra.append(f"by {t.finish:%d %b}")
            if t.priority.strip().casefold() == "critical":
                extra.append("**critical**")
            tail = f" ({', '.join(extra)})" if extra else ""
            lines.append(f"{i}. `{t.id}` {t.title}{tail} · {owners(t)}")
    missed = [
        m
        for m in milestones
        if m.target and m.target < today and m.status.strip().casefold() != "done"
    ]
    for m in missed:
        lines.append(f"⚠️ **{m.gate}** was due {m.target:%d %b} and isn't marked done: {m.title}")
    gate = next_gate(milestones, today)
    if gate and gate.target:
        days = (gate.target - today).days
        when = "today" if days == 0 else f"in {_plural(days, 'day')}"
        pool = plan.open_tasks if open_tasks is None else open_tasks
        due = [t for t in pool if t.finish and t.finish <= gate.target]
        lead = f"🏁 **{gate.gate}** {when} ({gate.target:%d %b}): {gate.title}"
        lines.append(f"{lead}. {_plural(len(due), 'open task')} due by then." if due else lead)
    return lines
