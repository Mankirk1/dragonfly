"""Read and write the Google Sheet through gspread.

All methods here block; the bot calls them with ``asyncio.to_thread``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .config import Settings
from .sheet import (
    ADDED_HEADERS,
    LOG_ALIASES,
    LOG_HEADERS,
    Member,
    Milestone,
    Task,
    TaskTable,
    Week,
    find_table,
    is_everyone,
    looks_like_task_tab,
    next_ids,
    parse_calendar,
    parse_milestones,
    parse_task_values,
    parse_team,
    safe_cell,
    split_names,
)

log = logging.getLogger(__name__)

TEAM_HEADERS = ["Name", "Discord ID"]


def _a1(row: int, col: int) -> str:
    """1-based row and column to A1 notation."""
    letters = ""
    while col:
        col, rem = divmod(col - 1, 26)
        letters = chr(65 + rem) + letters
    return f"{letters}{row}"


def open_spreadsheet(settings: Settings) -> Any:
    import gspread  # imported here so the pure modules can be tested without it

    client = gspread.service_account_from_dict(settings.google_credentials())
    return client.open_by_key(settings.sheet_id)


@dataclass
class Calendar:
    weeks: list[Week] = field(default_factory=list)
    milestones: list[Milestone] = field(default_factory=list)

    @property
    def start(self) -> date | None:
        first = next((w for w in self.weeks if w.number == 1), None)
        return first.start if first else None

    def week(self, number: int) -> Week | None:
        return next((w for w in self.weeks if w.number == number), None)


class SheetStore:
    def __init__(self, spreadsheet: Any, settings: Settings) -> None:
        self.book = spreadsheet
        self.settings = settings
        self._tasks_title: str | None = None

    # -- worksheets -------------------------------------------------------------

    def _find_tab(self, title: str) -> Any | None:
        for ws in self.book.worksheets():
            if ws.title.strip().casefold() == title.strip().casefold():
                return ws
        return None

    def _tab(self, title: str, headers: list[str] | None = None) -> Any:
        ws = self._find_tab(title)
        if ws is not None:
            return ws
        if headers is None:
            raise LookupError(f'No tab called "{title}"')
        log.info("Creating the %s tab", title)
        ws = self.book.add_worksheet(title=title, rows=100, cols=len(headers))
        ws.batch_update([{"range": "A1", "values": [headers]}], value_input_option="RAW")
        return ws

    def _tasks_ws(self) -> Any:
        if self.settings.tasks_tab:
            return self._tab(self.settings.tasks_tab)
        if self._tasks_title:
            ws = self._find_tab(self._tasks_title)
            if ws is not None:
                return ws
        for ws in self.book.worksheets():
            if looks_like_task_tab(ws.get_all_values(), self.settings.columns):
                self._tasks_title = ws.title
                return ws
        raise LookupError("No tab in the Sheet looks like a task list")

    def _append(self, ws: Any, values: list[str]) -> None:
        """Write a row under the last non-empty row (safer than guessing the table)."""
        row = len(ws.get_all_values()) + 1
        if row > ws.row_count:
            ws.add_rows(row - ws.row_count + 20)
        if len(values) > ws.col_count:
            ws.add_cols(len(values) - ws.col_count)
        ws.batch_update(
            [{"range": _a1(row, 1), "values": [values]}], value_input_option="USER_ENTERED"
        )

    # -- calendar ---------------------------------------------------------------

    def load_calendar(self) -> Calendar:
        cal = Calendar()
        ws = self._find_tab(self.settings.checkin_tab)
        if ws is not None:
            cal.weeks, _ = parse_calendar(ws.get_all_values(), self.settings.day_first)
        ws = self._find_tab(self.settings.milestones_tab)
        if ws is not None:
            cal.milestones = parse_milestones(ws.get_all_values(), self.settings.day_first)
        return cal

    def project_start(self, cal: Calendar | None = None) -> date | None:
        if self.settings.project_start:
            return self.settings.project_start
        return (cal or self.load_calendar()).start

    def fill_checkin(self, week: int, completed: str, moved: str) -> bool:
        """Fill a week's "completed" and "moved" cells, but only where they're empty."""
        ws = self._find_tab(self.settings.checkin_tab)
        if ws is None:
            return False
        values = ws.get_all_values()
        weeks, cols = parse_calendar(values, self.settings.day_first)
        target = next((w for w in weeks if w.number == week), None)
        if target is None:
            return False
        row = values[target.row - 1]
        data = []
        for name, text in (("completed", completed), ("moved", moved)):
            idx = cols.get(name)
            if idx is None or not text:
                continue
            if idx < len(row) and str(row[idx]).strip():
                continue
            data.append({"range": _a1(target.row, idx + 1), "values": [[safe_cell(text)]]})
        if data:
            ws.batch_update(data, value_input_option="USER_ENTERED")
        return bool(data)

    # -- tasks ------------------------------------------------------------------

    def load_tasks(self, project_start: date | None = None) -> TaskTable:
        """Read the plan, adding missing ID / owner / status columns and IDs the first time."""
        start = project_start or self.project_start()
        ws = self._tasks_ws()
        table = parse_task_values(ws.get_all_values(), self.settings, start)
        if not self.settings.auto_add_columns:
            return table
        if self._add_missing_columns(ws, table):
            table = parse_task_values(ws.get_all_values(), self.settings, start)
        ids = next_ids(table.tasks)
        if ids:
            col = table.columns["id"] + 1
            ws.batch_update(
                [{"range": _a1(row, col), "values": [[tid]]} for row, tid in ids.items()],
                value_input_option="RAW",
            )
            for t in table.tasks:
                t.id = ids.get(t.row, t.id)
        return table

    def _add_missing_columns(self, ws: Any, table: TaskTable) -> bool:
        missing = [name for name in ADDED_HEADERS if name not in table.columns]
        if not missing:
            return False
        start = len(table.headers) + 1
        need = start + len(missing) - 1
        if need > ws.col_count:
            ws.add_cols(need - ws.col_count)
        ws.batch_update(
            [
                {"range": _a1(table.header_row, start + i), "values": [[ADDED_HEADERS[name]]]}
                for i, name in enumerate(missing)
            ],
            value_input_option="RAW",
        )
        log.info("Added columns to the plan: %s", ", ".join(ADDED_HEADERS[m] for m in missing))
        return True

    def update_task(self, task_id: str, changes: dict[str, str]) -> Task:
        """Write ``changes`` ({field: value}) to the task's row, read fresh from the sheet.

        A ``progress`` change is added to what's already in that cell rather than replacing it.
        """
        ws = self._tasks_ws()
        table = parse_task_values(ws.get_all_values(), self.settings, self.project_start())
        task = table.find(task_id)
        if task is None:
            raise KeyError(task_id)
        data = []
        for name, value in changes.items():
            col = table.column(name)
            if col is None:
                continue
            if name == "status":
                value = self._status_value(task.status, value)
            if name == "progress" and task.progress and value:
                value = f"{task.progress}; {value}"
            data.append({"range": _a1(task.row, col + 1), "values": [[safe_cell(value)]]})
            if name == "assignee":
                task.assignees = split_names(value)
            elif hasattr(task, name):
                setattr(task, name, value)
        if data:
            ws.batch_update(data, value_input_option="USER_ENTERED")
        return task

    def _status_value(self, current: str, wanted: str) -> str:
        # Keep checkbox columns as checkboxes.
        if current.upper() in ("TRUE", "FALSE"):
            return "TRUE" if wanted == self.settings.done_label else "FALSE"
        return wanted

    def assign_many(self, assignments: dict[str, list[str]]) -> None:
        if not assignments:
            return
        ws = self._tasks_ws()
        table = parse_task_values(ws.get_all_values(), self.settings, self.project_start())
        col = table.column("assignee")
        if col is None:
            return
        data = []
        for task_id, names in assignments.items():
            task = table.find(task_id)
            if task is not None and not task.assignees:
                data.append(
                    {"range": _a1(task.row, col + 1), "values": [[safe_cell(" + ".join(names))]]}
                )
        if data:
            ws.batch_update(data, value_input_option="USER_ENTERED")

    # -- team -------------------------------------------------------------------

    def load_team(self, seed_names: list[str] | None = None) -> list[Member]:
        """Read the Team tab, creating it from the names in the plan if it's missing."""
        ws = self._find_tab(self.settings.team_tab)
        if ws is None:
            ws = self._tab(self.settings.team_tab, TEAM_HEADERS)
            names = sorted({n for n in seed_names or [] if not is_everyone(n)})
            if names:
                ws.batch_update(
                    [{"range": "A2", "values": [[safe_cell(n), ""] for n in names]}],
                    value_input_option="RAW",
                )
        return parse_team(ws.get_all_values())

    def link_member(self, name: str, discord_id: int) -> Member:
        ws = self._tab(self.settings.team_tab, TEAM_HEADERS)
        members = parse_team(ws.get_all_values())
        for m in members:
            if m.discord_id == discord_id and m.name.casefold() != name.casefold():
                ws.batch_update(
                    [{"range": _a1(m.row, 2), "values": [[""]]}], value_input_option="RAW"
                )
        for m in members:
            if m.name.casefold() == name.casefold():
                ws.batch_update(
                    [{"range": _a1(m.row, 2), "values": [[str(discord_id)]]}],
                    value_input_option="RAW",
                )
                return Member(row=m.row, name=m.name, discord_id=discord_id)
        self._append(ws, [safe_cell(name), str(discord_id)])
        return Member(row=len(members) + 2, name=name, discord_id=discord_id)

    # -- log --------------------------------------------------------------------

    def log(
        self,
        when: date,
        week_start: date | None,
        task: Task,
        action: str,
        by: str,
        status: str = "",
        note: str = "",
    ) -> None:
        """Add a row to the work log (the Sheet's own WORK LOG tab when it has one)."""
        ws = self._tab(self.settings.log_tab, LOG_HEADERS)
        values = ws.get_all_values()
        header, cols = find_table(values, LOG_ALIASES, ("task_id",))
        if header is None:
            raise LookupError(f"The {self.settings.log_tab} tab has no task ID column")
        fields = {
            "when": when.isoformat(),
            "week": week_start.isoformat() if week_start else "",
            "by": safe_cell(by),
            "task_id": task.id,
            "task": safe_cell(task.title),
            "action": safe_cell(action),
            "status": status,
            "note": safe_cell(note),
        }
        row = [""] * (max(cols.values()) + 1)
        for name, idx in cols.items():
            row[idx] = fields.get(name, "")
        self._append(ws, row)
