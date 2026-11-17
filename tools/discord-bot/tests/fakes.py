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
    def __init__(self, title: str, rows: list[list[str]], cols: int | None = None) -> None:
        self.title = title
        self.rows = [list(r) for r in rows]
        self.col_count = cols or max((len(r) for r in rows), default=1)
        self.row_count = max(len(rows), 100)

    def get_all_values(self) -> list[list[str]]:
        width = max((len(r) for r in self.rows), default=0)
        return [r + [""] * (width - len(r)) for r in self.rows]

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
            for r, values in enumerate(item["values"]):
                for c, value in enumerate(values):
                    self._set(row + r, col + c, value)

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

    def worksheets(self) -> list[FakeWorksheet]:
        return self.sheets

    def add_worksheet(self, title: str, rows: int, cols: int) -> FakeWorksheet:
        ws = FakeWorksheet(title, [], cols)
        self.sheets.append(ws)
        return ws
