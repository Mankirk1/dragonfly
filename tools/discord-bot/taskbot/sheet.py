"""Read the plan out of grids of cell values.

Everything here is pure: it takes the rows a spreadsheet returns (lists of strings)
and gives back tasks, weeks and milestones. Talking to Google lives in ``store.py``.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .config import Columns, Settings

FIELDS = (
    "id",
    "week",
    "start",
    "finish",
    "task",
    "assignee",
    "status",
    "due",
    "signed_off_by",
    "signed_off_at",
    "last_updated",
    "progress",
    "workstream",
    "priority",
)

# Header names we recognise for each field, matched without case and without any
# "(...)" part, so "Owner(s)" reads as "owner". Checked in order.
ALIASES: dict[str, tuple[str, ...]] = {
    "id": ("id", "task id", "ref", "#"),
    "week": ("week", "weeks", "wk", "week #", "week no", "week number", "semaine", "sprint"),
    "start": ("target start", "start", "start date", "planned start", "begin"),
    "finish": ("target finish", "finish", "end", "end date", "target end", "planned finish"),
    "task": (
        "planned task",
        "task",
        "tasks",
        "task name",
        "description",
        "activity",
        "deliverable",
        "item",
        "to do",
    ),
    "assignee": (
        "owner",
        "owners",
        "assigned to",
        "assignee",
        "assignees",
        "responsible",
        "who",
        "member",
        "person",
    ),
    "status": ("status", "state", "done", "complete", "completed"),
    "due": ("due", "due date", "deadline"),
    "signed_off_by": ("signed off by", "completed by", "approved by"),
    "signed_off_at": (
        "completion date",
        "signed off at",
        "signed off on",
        "sign off date",
        "completed on",
        "completed at",
        "date completed",
    ),
    "last_updated": ("last updated", "updated", "last update"),
    "progress": (
        "what changed / actual progress",
        "actual progress",
        "progress notes",
        "progress",
    ),
    "workstream": ("workstream", "category", "area", "phase"),
    "priority": ("priority",),
}

# Columns the bot adds when they're missing and auto_add_columns is on.
ADDED_HEADERS = {
    "id": "ID",
    "assignee": "Owner(s)",
    "status": "Status",
    "signed_off_at": "Completion date",
}

EVERYONE = ("all", "everyone", "team", "whole team", "tous")

_SPLIT_NAMES = re.compile(r"\s*(?:,|/|&|;|\+|\band\b|\bet\b)\s*", re.IGNORECASE)
_PARENS = re.compile(r"\([^)]*\)")


class SheetFormatError(ValueError):
    """The task tab doesn't have the columns the bot needs."""


@dataclass
class Task:
    row: int  # 1-based row in the sheet
    id: str
    title: str
    week: int | None
    week_end: int | None
    assignees: list[str] = field(default_factory=list)
    status: str = ""
    due: str = ""
    start: date | None = None
    finish: date | None = None
    signed_off_by: str = ""
    signed_off_at: str = ""
    progress: str = ""
    workstream: str = ""
    priority: str = ""

    def is_done(self, done_values: tuple[str, ...]) -> bool:
        return self.status.strip().casefold() in done_values

    def is_closed(self, closed_values: tuple[str, ...]) -> bool:
        return self.status.strip().casefold() in closed_values

    def active_in(self, week: int) -> bool:
        if self.week is None:
            return False
        return self.week <= week <= (self.week_end or self.week)

    def overdue_in(self, week: int) -> bool:
        if self.week is None:
            return False
        return (self.week_end or self.week) < week


@dataclass
class TaskTable:
    header_row: int  # 1-based
    headers: list[str]
    columns: dict[str, int]  # field -> 0-based column index
    tasks: list[Task]

    def column(self, name: str) -> int | None:
        return self.columns.get(name)

    def find(self, task_id: str) -> Task | None:
        wanted = task_id.strip().casefold()
        return next((t for t in self.tasks if t.id.casefold() == wanted), None)


@dataclass
class Member:
    row: int
    name: str
    discord_id: int | None


@dataclass
class Week:
    number: int
    start: date
    end: date
    focus: str = ""
    row: int = 0


@dataclass
class Milestone:
    gate: str
    target: date | None
    title: str
    status: str


# -- small helpers ------------------------------------------------------------------


def normalise(text: str) -> str:
    text = _PARENS.sub(" ", str(text)).replace("_", " ").rstrip("?: ")
    return " ".join(text.split()).casefold()


def parse_date(text: str, day_first: bool = True) -> date | None:
    text = str(text).strip()
    if not text:
        return None
    slash = ("%d/%m/%Y", "%d/%m/%y", "%m/%d/%Y", "%m/%d/%y")
    if not day_first:
        slash = slash[2:] + slash[:2]
    formats = (
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d",
        *slash,
        "%d.%m.%Y",
        "%d-%m-%Y",
        "%d %b %Y",
        "%d %B %Y",
        "%b %d, %Y",
        "%B %d, %Y",
        "%d-%b-%Y",
        "%a, %d %b %Y",
    )
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()  # noqa: DTZ007 - a calendar date
        except ValueError:
            continue
    return None


def week_of(day: date | None, project_start: date | None) -> int | None:
    if day is None or project_start is None:
        return None
    return (day - project_start).days // 7 + 1


def parse_week(
    cell: str, project_start: date | None, day_first: bool = True
) -> tuple[int | None, int | None]:
    """Read "Week 3", "3", "W2-4", "Weeks 5 to 6" or a date into (first, last) week."""
    text = str(cell).strip()
    if not text:
        return None, None
    day = parse_date(text, day_first)
    if day is not None:
        week = week_of(day, project_start)
        return week, week
    numbers = [int(n) for n in re.findall(r"\d+", text)]
    if not numbers:
        return None, None
    return numbers[0], max(numbers[0], numbers[-1])


def split_names(cell: str) -> list[str]:
    return [n for n in _SPLIT_NAMES.split(str(cell).strip()) if n]


def is_everyone(name: str) -> bool:
    return normalise(name) in EVERYONE


def safe_cell(value: str) -> str:
    """Stop text typed in Discord from being read as a spreadsheet formula."""
    if value and value[0] in "=+-@":
        return "'" + value
    return value


def short_date(day: date | None) -> str:
    return day.strftime("%d %b") if day else ""


# -- header detection ---------------------------------------------------------------


def map_headers(
    headers: list[str], aliases: dict[str, tuple[str, ...]], configured: dict[str, str]
) -> dict[str, int]:
    """Work out which column holds each field."""
    clean = [normalise(h) for h in headers]
    taken: set[int] = set()
    found: dict[str, int] = {}
    for name, wanted in configured.items():  # configured names can't be claimed by aliases
        if not wanted:
            continue
        key = normalise(wanted)
        if key not in clean:
            raise SheetFormatError(f'No column called "{wanted}"')
        found[name] = clean.index(key)
        taken.add(found[name])
    for name, names in aliases.items():
        if name in found:
            continue
        for alias in names:
            idx = next((i for i, h in enumerate(clean) if h == alias and i not in taken), None)
            if idx is not None:
                found[name] = idx
                taken.add(idx)
                break
    return found


def map_columns(headers: list[str], configured: Columns) -> dict[str, int]:
    wanted = {name: getattr(configured, name, "") for name in FIELDS}
    return map_headers(headers, ALIASES, wanted)


def _is_task_header(cols: dict[str, int]) -> bool:
    return "task" in cols and ("week" in cols or "start" in cols or "finish" in cols)


def find_header_row(values: list[list[str]], configured: Columns, header_row: int = 0) -> int:
    """Return the 1-based header row: the first of the top 10 that names tasks and timing."""
    if header_row:
        return header_row
    for i, row in enumerate(values[:10]):
        try:
            cols = map_columns(row, configured)
        except SheetFormatError:
            continue
        if _is_task_header(cols):
            return i + 1
    raise SheetFormatError(
        "Couldn't find a header row with a task column and a week or target date column "
        "in the first 10 rows. Set TASKBOT_COL_TASK / TASKBOT_COL_WEEK or TASKBOT_HEADER_ROW."
    )


def looks_like_task_tab(values: list[list[str]], configured: Columns) -> bool:
    try:
        find_header_row(values, configured)
    except SheetFormatError:
        return False
    return True


# -- tabs ---------------------------------------------------------------------------


def parse_tasks(
    values: list[list[str]],
    configured: Columns,
    project_start: date | None = None,
    header_row: int = 0,
    day_first: bool = True,
) -> TaskTable:
    header_row = find_header_row(values, configured, header_row)
    headers = [str(h) for h in values[header_row - 1]] if len(values) >= header_row else []
    cols = map_columns(headers, configured)
    if not _is_task_header(cols):
        raise SheetFormatError("The task tab needs a task column and a week or date column")

    def cell(row: list[str], name: str) -> str:
        idx = cols.get(name)
        if idx is None or idx >= len(row):
            return ""
        return str(row[idx]).strip()

    tasks: list[Task] = []
    week: tuple[int | None, int | None] = (None, None)
    for offset, row in enumerate(values[header_row:]):
        row_number = header_row + 1 + offset
        start = parse_date(cell(row, "start"), day_first)
        finish = parse_date(cell(row, "finish"), day_first)
        if "week" in cols:
            # Merged week cells only hold a value on their first row, so carry it down.
            week_cell = cell(row, "week")
            if week_cell:
                week = parse_week(week_cell, project_start, day_first)
            this_week = week
        else:
            first = week_of(start or finish, project_start)
            last = week_of(finish or start, project_start)
            this_week = (first, max(first, last) if first and last else last)
        title = cell(row, "task")
        if not title:
            continue
        tasks.append(
            Task(
                row=row_number,
                id=cell(row, "id"),
                title=title,
                week=this_week[0],
                week_end=this_week[1],
                assignees=split_names(cell(row, "assignee")),
                status=cell(row, "status"),
                due=cell(row, "due") or short_date(finish),
                start=start,
                finish=finish,
                signed_off_by=cell(row, "signed_off_by"),
                signed_off_at=cell(row, "signed_off_at"),
                progress=cell(row, "progress"),
                workstream=cell(row, "workstream"),
                priority=cell(row, "priority"),
            )
        )
    return TaskTable(header_row=header_row, headers=headers, columns=cols, tasks=tasks)


def parse_task_values(
    values: list[list[str]], settings: Settings, project_start: date | None = None
) -> TaskTable:
    return parse_tasks(
        values,
        settings.columns,
        project_start or settings.project_start,
        settings.header_row,
        settings.day_first,
    )


def next_ids(tasks: list[Task]) -> dict[int, str]:
    """IDs for tasks that have none, as {row: "R39"}, following the existing pattern."""
    pattern = re.compile(r"([A-Za-z]*)(\d+)")
    seen = [m for t in tasks if (m := pattern.fullmatch(t.id))]
    prefix = Counter(m.group(1) for m in seen).most_common(1)[0][0] if seen else "T"
    width = max((len(m.group(2)) for m in seen if m.group(1) == prefix), default=1)
    highest = max((int(m.group(2)) for m in seen if m.group(1) == prefix), default=0)
    out: dict[int, str] = {}
    for t in tasks:
        if not t.id:
            highest += 1
            out[t.row] = f"{prefix}{highest:0{width}d}"
    return out


def parse_team(values: list[list[str]]) -> list[Member]:
    """Read the Team tab: a Name column and a Discord ID column, header in row 1."""
    if not values:
        return []
    clean = [normalise(h) for h in values[0]]
    name_idx = next((i for i, h in enumerate(clean) if h in ("name", "member", "who")), 0)
    id_idx = next((i for i, h in enumerate(clean) if "discord" in h), 1)
    members = []
    for offset, row in enumerate(values[1:]):
        name = str(row[name_idx]).strip() if name_idx < len(row) else ""
        if not name:
            continue
        raw_id = str(row[id_idx]).strip() if id_idx < len(row) else ""
        members.append(
            Member(row=offset + 2, name=name, discord_id=int(raw_id) if raw_id.isdigit() else None)
        )
    return members


def match_member(name: str, members: list[Member]) -> Member | None:
    """Match a name from the plan to a team member: exact, then by first name."""
    key = normalise(name)
    if not key:
        return None
    for m in members:
        if normalise(m.name) == key:
            return m
    first = key.split()[0]
    hits = [m for m in members if normalise(m.name).split()[0] == first]
    return hits[0] if len(hits) == 1 else None


def people_for(names: list[str], team: list[Member]) -> list[Member]:
    """Team members a task's owners refer to, with "All" meaning everyone."""
    out: list[Member] = []
    for name in names:
        group = team if is_everyone(name) else [m for m in [match_member(name, team)] if m]
        for m in group:
            if m not in out:
                out.append(m)
    return out


_WEEK_ALIASES = {
    "week": ("week", "wk", "week #"),
    "start": ("week starts", "week start", "week beginning", "start", "from"),
    "end": ("week ends", "week end", "end", "to"),
    "focus": ("suggested focus", "focus", "agreed team priorities", "priorities"),
    "completed": ("what we actually completed", "completed", "done"),
    "moved": ("work moved / new week", "work moved", "carried over"),
}


def find_table(values: list[list[str]], aliases: dict, required: tuple[str, ...]):  # noqa: ANN201
    """Find a header row in the top 10 rows holding ``required`` fields."""
    for i, row in enumerate(values[:10]):
        cols = map_headers([str(c) for c in row], aliases, {})
        if all(r in cols for r in required):
            return i + 1, cols
    return None, {}


def parse_calendar(values: list[list[str]], day_first: bool = True) -> tuple[list[Week], dict]:
    """Read a weekly check-in tab: one row per week with its start and end dates."""
    header, cols = find_table(values, _WEEK_ALIASES, ("week", "start"))
    if header is None:
        return [], {}
    weeks = []
    for offset, row in enumerate(values[header:]):

        def cell(name: str, row: list[str] = row) -> str:
            idx = cols.get(name)
            return str(row[idx]).strip() if idx is not None and idx < len(row) else ""

        numbers = re.findall(r"\d+", cell("week"))
        start = parse_date(cell("start"), day_first)
        if not numbers or start is None:
            continue
        end = parse_date(cell("end"), day_first) or start + timedelta(days=6)
        weeks.append(Week(int(numbers[0]), start, end, cell("focus"), row=header + 1 + offset))
    return weeks, cols


_MILESTONE_ALIASES = {
    "gate": ("gate", "milestone id", "id"),
    "target": ("target date", "date", "due"),
    "title": ("milestone / acceptance criteria", "milestone", "description"),
    "status": ("status",),
}


def parse_milestones(values: list[list[str]], day_first: bool = True) -> list[Milestone]:
    header, cols = find_table(values, _MILESTONE_ALIASES, ("target", "title"))
    if header is None:
        return []
    out = []
    for row in values[header:]:

        def cell(name: str, row: list[str] = row) -> str:
            idx = cols.get(name)
            return str(row[idx]).strip() if idx is not None and idx < len(row) else ""

        if cell("title"):
            out.append(
                Milestone(
                    cell("gate"),
                    parse_date(cell("target"), day_first),
                    cell("title"),
                    cell("status"),
                )
            )
    return out


LOG_ALIASES = {
    "when": ("date", "when", "timestamp"),
    "week": ("week beginning", "week starts", "week"),
    "by": ("member", "by", "who", "person"),
    "task_id": ("related task id", "task id", "id"),
    "task": ("planned for this session", "task"),
    "action": ("what was actually done", "action", "what happened"),
    "status": ("status / result", "status", "result"),
    "note": ("blocker / comments", "note", "notes", "comments"),
}
LOG_HEADERS = ["Date", "Week beginning", "Member", "Related task ID", "Task", "Action", "Status",
               "Note"]  # fmt: skip
