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


# The only task fields the bot ever writes. ID, task name, dates, priority and the rest
# of the plan are never touched.
WRITABLE_FIELDS = frozenset(
    {"status", "assignee", "signed_off_at", "signed_off_by", "last_updated", "progress"}
)


class UnsafeWriteError(RuntimeError):
    """A write was stopped because it could have damaged the Sheet."""


def open_spreadsheet(settings: Settings) -> Any:
    import gspread  # imported here so the pure modules can be tested without it

    from .gcp import sheets_credentials

    client = gspread.authorize(sheets_credentials(settings))
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

    def _tab(self, title: str, headers: list[str] | None = None, own: bool = False) -> Any:
        """Find a tab, creating it with ``headers`` if it's missing.

        ``own`` marks the bot's own TEAM tab, which read-only mode still lets it create
        and edit, so people can /link while the plan itself is left alone.
        """
        ws = self._find_tab(title)
        if ws is not None:
            return ws
        if headers is None:
            raise LookupError(f'No tab called "{title}"')
        if self.settings.read_only and not own:
            raise UnsafeWriteError(f'Read-only: would create a "{title}" tab')
        log.info("Creating the %s tab", title)
        ws = self.book.add_worksheet(title=title, rows=100, cols=len(headers))
        self._write(ws, [(1, c + 1, h) for c, h in enumerate(headers)], raw=True, own=own)
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

    # -- guarded writes ---------------------------------------------------------
    #
    # Every write goes through _write. It sends single cells only (never ranges that
    # could clear neighbours), and in read-only mode it only logs what it would do.

    def _write(
        self, ws: Any, cells: list[tuple[int, int, str]], raw: bool = False, own: bool = False
    ) -> None:
        """Write (row, col, value) cells, 1-based."""
        if not cells:
            return
        if self.settings.read_only and not own:
            for row, col, value in cells:
                log.info("Read-only: would write %r to %s!%s", value, ws.title, _a1(row, col))
            return
        ws.batch_update(
            [{"range": _a1(r, c), "values": [[v]]} for r, c, v in cells],
            value_input_option="RAW" if raw else "USER_ENTERED",
        )

    def _formulas(self, ws: Any, row: int) -> list[str]:
        """The row as typed (formulas, not their results)."""
        return [str(v) for v in ws.row_values(row, value_render_option="FORMULA")]

    def _cell_is_free(
        self, values: list[list[str]], formulas: list[str], row: int, col: int
    ) -> bool:
        """True when a cell holds nothing at all: no value and no formula."""
        shown = (
            values[row - 1][col - 1] if row <= len(values) and col <= len(values[row - 1]) else ""
        )
        typed = formulas[col - 1] if col <= len(formulas) else ""
        return not str(shown).strip() and not str(typed).strip()

    def _append(self, ws: Any, values: list[str], own: bool = False) -> None:
        """Write a new row below everything else, never over an existing row."""
        existing = ws.get_all_values()
        row = len(existing) + 1
        for _ in range(50):  # skip rows that only look empty, e.g. formulas showing ""
            if row > ws.row_count or not any(v.strip() for v in self._formulas(ws, row)):
                break
            row += 1
        else:
            raise UnsafeWriteError(f"Couldn't find an empty row in {ws.title}")
        if self.settings.read_only and not own:
            log.info("Read-only: would add row %d to %s: %r", row, ws.title, values)
            return
        if row > ws.row_count:
            ws.add_rows(row - ws.row_count + 20)
        if len(values) > ws.col_count:
            ws.add_cols(len(values) - ws.col_count)
        self._write(ws, [(row, c + 1, v) for c, v in enumerate(values) if v != ""], own=own)

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
        formulas = self._formulas(ws, target.row)
        cells = []
        for name, text in (("completed", completed), ("moved", moved)):
            idx = cols.get(name)
            if idx is None or not text:
                continue
            if self._cell_is_free(values, formulas, target.row, idx + 1):
                cells.append((target.row, idx + 1, safe_cell(text)))
        self._write(ws, cells)
        return bool(cells)

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
        if ids and "id" in table.columns:
            values = ws.get_all_values()
            col = table.columns["id"] + 1
            cells = [
                (row, col, tid)
                for row, tid in ids.items()
                if self._cell_is_free(values, self._formulas(ws, row), row, col)
            ]
            self._write(ws, cells, raw=True)
            for row, _, tid in cells:
                t = next(t for t in table.tasks if t.row == row)
                t.id = tid
        return table

    def _add_missing_columns(self, ws: Any, table: TaskTable) -> bool:
        missing = [name for name in ADDED_HEADERS if name not in table.columns]
        if not missing:
            return False
        start = len(table.headers) + 1
        while start > 1 and not str(table.headers[start - 2]).strip():
            start -= 1  # header rows are often padded with blanks
        values = ws.get_all_values()
        for col in range(start, start + len(missing)):
            if any(col <= len(r) and str(r[col - 1]).strip() for r in values):
                log.warning("Not adding columns: column %d already holds something", col)
                return False
        need = start + len(missing) - 1
        if need > ws.col_count:
            ws.add_cols(need - ws.col_count)
        self._write(
            ws,
            [(table.header_row, start + i, ADDED_HEADERS[name]) for i, name in enumerate(missing)],
            raw=True,
        )
        if self.settings.read_only:
            return False
        log.info("Added columns to the plan: %s", ", ".join(ADDED_HEADERS[m] for m in missing))
        return True

    def update_task(
        self,
        task_id: str,
        changes: dict[str, str],
        expected_title: str | None = None,
        only_if_blank: frozenset[str] = frozenset(),
    ) -> Task:
        """Write ``changes`` ({field: value}) into one task's row, with safety checks.

        Read fresh from the Sheet first, then refuse unless: the ID is found exactly once,
        the row still holds the expected task, every field is one the bot may write, no
        target cell holds a formula, no value would blank a filled cell, and a status is
        one of the dropdown's options. A ``progress`` note is added to the cell, never
        replacing it. Fields in ``only_if_blank`` are skipped when already filled.
        """
        ws = self._tasks_ws()
        values = ws.get_all_values()
        table = parse_task_values(values, self.settings, self.project_start())
        matches = [t for t in table.tasks if t.id.casefold() == task_id.strip().casefold()]
        if not matches:
            raise KeyError(task_id)
        if len(matches) > 1:
            raise UnsafeWriteError(f"{task_id} appears on more than one row, so I won't edit it")
        task = matches[0]
        if expected_title is not None and task.title != expected_title:
            raise UnsafeWriteError(
                f"{task_id}'s row changed since it was read, so I didn't edit it. Try again."
            )
        formulas = self._formulas(ws, task.row)
        protected = {table.column(f) for f in ("id", "task", "week", "start", "finish")}
        cells: list[tuple[int, int, str]] = []
        for name, value in changes.items():
            if name not in WRITABLE_FIELDS:
                raise UnsafeWriteError(f"The bot doesn't edit the {name} column")
            idx = table.column(name)
            if idx is None:
                continue
            if idx in protected:
                raise UnsafeWriteError(f"The {name} column overlaps a column the bot never edits")
            col = idx + 1
            current = values[task.row - 1][idx] if idx < len(values[task.row - 1]) else ""
            typed = formulas[idx] if idx < len(formulas) else ""
            if str(typed).startswith("="):
                cell = _a1(task.row, col)
                raise UnsafeWriteError(f"{cell} holds a formula, so I won't overwrite it")
            if name in only_if_blank and str(current).strip():
                continue
            if name == "status":
                value = self._status_value(task.status, value)
            if name == "progress" and value and str(current).strip():
                value = f"{current}; {value}"
            if not str(value).strip() and str(current).strip():
                raise UnsafeWriteError(f"I won't blank {_a1(task.row, col)}")
            if str(value) == str(current):
                continue
            cells.append((task.row, col, safe_cell(str(value))))
            if name == "assignee":
                task.assignees = split_names(value)
            elif hasattr(task, name):
                setattr(task, name, value)
        self._write(ws, cells)
        if cells and not self.settings.read_only:
            self._verify(ws, task)
        return task

    def _verify(self, ws: Any, task: Task) -> None:
        """Re-read the row after writing and check it still belongs to the same task."""
        values = ws.get_all_values()
        table = parse_task_values(values, self.settings, self.project_start())
        after = next((t for t in table.tasks if t.row == task.row), None)
        if after is None or after.id != task.id or after.title != task.title:
            log.error(
                "Row %d no longer matches %s after writing; check the Sheet", task.row, task.id
            )
            raise UnsafeWriteError(
                f"{task.id}'s row looked different after the edit. Please check it."
            )

    def _status_value(self, current: str, wanted: str) -> str:
        # Keep checkbox columns as checkboxes.
        if current.upper() in ("TRUE", "FALSE"):
            return "TRUE" if wanted == self.settings.done_label else "FALSE"
        allowed = {v.casefold(): v for v in self.settings.status_values}
        if wanted.casefold() not in allowed:
            raise UnsafeWriteError(f'"{wanted}" isn\'t one of the Status options')
        return allowed[wanted.casefold()]

    def assign_many(self, assignments: dict[str, list[str]], titles: dict[str, str]) -> None:
        """Fill in owners for tasks that have none. Never replaces an existing owner."""
        for task_id, names in assignments.items():
            try:
                self.update_task(
                    task_id,
                    {"assignee": " + ".join(names)},
                    expected_title=titles.get(task_id),
                    only_if_blank=frozenset({"assignee"}),
                )
            except (UnsafeWriteError, KeyError) as exc:
                log.warning("Didn't assign %s: %s", task_id, exc)

    # -- team -------------------------------------------------------------------

    def load_team(self, seed_names: list[str] | None = None) -> list[Member]:
        """Read the Team tab, creating it from the names in the plan if it's missing."""
        ws = self._find_tab(self.settings.team_tab)
        if ws is None:
            ws = self._tab(self.settings.team_tab, TEAM_HEADERS, own=True)
            names = sorted({n for n in seed_names or [] if not is_everyone(n)})
            self._write(ws, [(i + 2, 1, safe_cell(n)) for i, n in enumerate(names)], own=True)
        return parse_team(ws.get_all_values())

    def link_member(self, name: str, discord_id: int) -> Member:
        ws = self._tab(self.settings.team_tab, TEAM_HEADERS, own=True)
        members = parse_team(ws.get_all_values())
        # The TEAM tab is the bot's own, so it may move a Discord ID between names here.
        for m in members:
            if m.discord_id == discord_id and m.name.casefold() != name.casefold():
                self._write(ws, [(m.row, 2, "")], raw=True, own=True)
        for m in members:
            if m.name.casefold() == name.casefold():
                self._write(ws, [(m.row, 2, str(discord_id))], raw=True, own=True)
                return Member(row=m.row, name=m.name, discord_id=discord_id)
        self._append(ws, [safe_cell(name), str(discord_id)], own=True)
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
