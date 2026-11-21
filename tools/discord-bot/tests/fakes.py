"""In-memory stand-ins for gspread's Spreadsheet and Worksheet."""

from __future__ import annotations

import re


def _parse_a1(a1: str) -> tuple[int, int]:
    m = re.fullmatch(r"([A-Z]+)(\d+)", a1)
    assert m, a1
    col = 0
    for ch in m.group(1):
        col = col * 26 + (ord(ch) - 64)
    return int(m.group(2)), col


class FakeWorksheet:
    """Cells hold what's typed. A typed formula shows as ``shown`` (default "")."""

    def __init__(
        self,
        title: str,
        rows: list[list[str]],
        cols: int | None = None,
        shown: dict[tuple[int, int], str] | None = None,
    ) -> None:
        self.title = title
        self.rows = [list(r) for r in rows]
        self.shown = dict(shown or {})
        self.writes: list[tuple[int, int, str]] = []
        self.col_count = cols or max((len(r) for r in rows), default=1)
        self.row_count = max(len(rows), 100)
        self.reads = 0  # API reads, to keep within Google's 60-a-minute limit

    def get_all_values(self) -> list[list[str]]:
        self.reads += 1
        shown = [
            [
                self.shown.get((i + 1, j + 1), "") if str(v).startswith("=") else v
                for j, v in enumerate(r)
            ]
            for i, r in enumerate(self.rows)
        ]
        while shown and not any(str(v).strip() for v in shown[-1]):
            shown.pop()
        width = max((len(r) for r in shown), default=0)
        return [r + [""] * (width - len(r)) for r in shown]

    def row_values(self, row: int, value_render_option: str = "FORMATTED_VALUE") -> list[str]:
        assert value_render_option == "FORMULA"
        self.reads += 1
        values = list(self.rows[row - 1]) if row <= len(self.rows) else []
        while values and values[-1] == "":
            values.pop()
        return values

    def _set(self, row: int, col: int, value: str) -> None:
        assert col <= self.col_count, "write past the last column"
        assert row <= self.row_count, "write past the last row"
        while len(self.rows) < row:
            self.rows.append([])
        r = self.rows[row - 1]
        while len(r) < col:
            r.append("")
        r[col - 1] = value

    def batch_update(self, data: list[dict], value_input_option: str = "RAW") -> None:
        for item in data:
            row, col = _parse_a1(item["range"])
            assert len(item["values"]) == 1 and len(item["values"][0]) == 1, "single cells only"
            self._set(row, col, item["values"][0][0])
            self.writes.append((row, col, item["values"][0][0]))

    def add_cols(self, n: int) -> None:
        self.col_count += n

    def add_rows(self, n: int) -> None:
        self.row_count += n

    def append_row(self, values: list[str], value_input_option: str = "RAW") -> None:
        self.col_count = max(self.col_count, len(values))
        self.rows.append(list(values))


class FakeBook:
    def __init__(self, *sheets: FakeWorksheet) -> None:
        self.sheets = list(sheets)
        self.reads = 0

    def worksheets(self) -> list[FakeWorksheet]:
        self.reads += 1
        return list(self.sheets)

    def total_reads(self) -> int:
        return self.reads + sum(ws.reads for ws in self.sheets)

    def add_worksheet(self, title: str, rows: int, cols: int) -> FakeWorksheet:
        ws = FakeWorksheet(title, [], cols)
        self.sheets.append(ws)
        return ws
