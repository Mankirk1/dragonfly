"""The bot must never damage the plan: these pin down every safeguard on writes."""

import copy
from datetime import date

import pytest
from taskbot.config import Settings
from taskbot.store import SheetStore, UnsafeWriteError

from .fakes import FakeBook, FakeWorksheet
from .test_layout import book


def snapshot(b):
    return {ws.title: copy.deepcopy(ws.rows) for ws in b.sheets}


def changed_cells(before, b):
    out = set()
    for ws in b.sheets:
        old = before.get(ws.title, [])
        for r in range(max(len(old), len(ws.rows))):
            a = old[r] if r < len(old) else []
            c = ws.rows[r] if r < len(ws.rows) else []
            for col in range(max(len(a), len(c))):
                va = a[col] if col < len(a) else ""
                vc = c[col] if col < len(c) else ""
                if va != vc:
                    out.add((ws.title, r + 1, col + 1))
    return out


def setup(**settings):
    b = book()
    store = SheetStore(b, Settings(**settings))
    return b, store


def test_sign_off_touches_only_its_own_cells_and_one_new_log_row():
    b, store = setup()
    store.load_tasks()
    before = snapshot(b)
    store.update_task(
        "X02",
        {"status": "Done", "signed_off_at": "2026-11-17", "last_updated": "2026-11-17",
         "progress": "Chose sensor"},
        expected_title="Task 2",
    )  # fmt: skip
    task = next(t for t in store.load_tasks().tasks if t.id == "X02")
    store.log(date(2026, 11, 17), date(2026, 11, 14), task, "Signed off", "Ana", "Done")
    changed = changed_cells(before, b)
    board = {(r, c) for t, r, c in changed if t == "TASK BOARD"}
    assert board == {(6, 10), (6, 11), (6, 13), (6, 15)}  # Status, progress, updated, done
    log_rows = {r for t, r, _ in changed if t == "WORK LOG"}
    assert log_rows == {6}  # one new row under the existing entry
    assert {t for t, _, _ in changed} == {"TASK BOARD", "WORK LOG"}


def test_refuses_when_the_row_now_holds_a_different_task():
    b, store = setup()
    b.sheets[1].rows[5][2] = "Someone renamed this"
    before = snapshot(b)
    with pytest.raises(UnsafeWriteError, match="changed"):
        store.update_task("X02", {"status": "Done"}, expected_title="Task 2")
    assert changed_cells(before, b) == set()


def test_refuses_duplicate_ids():
    b, store = setup()
    b.sheets[1].rows[6][0] = "X02"
    before = snapshot(b)
    with pytest.raises(UnsafeWriteError, match="more than one row"):
        store.update_task("X02", {"status": "Done"})
    assert changed_cells(before, b) == set()


def test_never_overwrites_a_formula():
    b, store = setup()
    b.sheets[1].rows[5][12] = "=TODAY()"
    b.sheets[1].shown[(6, 13)] = "2026-11-17"
    before = snapshot(b)
    with pytest.raises(UnsafeWriteError, match="formula"):
        store.update_task("X02", {"status": "Done", "last_updated": "2026-11-18"})
    assert changed_cells(before, b) == set()


def test_never_blanks_a_filled_cell():
    b, store = setup()
    b.sheets[1].rows[4][14] = "2026-11-13"
    with pytest.raises(UnsafeWriteError, match="blank"):
        store.update_task("X01", {"signed_off_at": ""})
    assert b.sheets[1].rows[4][14] == "2026-11-13"


@pytest.mark.parametrize("field", ["task", "id", "start", "finish", "priority", "week"])
def test_never_writes_plan_columns(field):
    b, store = setup()
    before = snapshot(b)
    with pytest.raises(UnsafeWriteError):
        store.update_task("X02", {field: "x"})
    assert changed_cells(before, b) == set()


def test_status_must_be_a_dropdown_option():
    b, store = setup()
    with pytest.raises(UnsafeWriteError, match="Status options"):
        store.update_task("X02", {"status": "Finished!"})
    store.update_task("X02", {"status": "in PROGRESS"})
    assert b.sheets[1].rows[5][9] == "In progress"


def test_progress_notes_are_added_never_replaced():
    b, store = setup()
    b.sheets[1].rows[5][10] = "Earlier notes"
    store.update_task("X02", {"progress": "New note"})
    assert b.sheets[1].rows[5][10] == "Earlier notes; New note"


def test_auto_assign_never_replaces_an_owner():
    b, store = setup()
    store.assign_many({"X02": ["Ben"], "X03": ["Ben"]}, {"X02": "Task 2", "X03": "Task 3"})
    assert b.sheets[1].rows[5][3] == "All" and b.sheets[1].rows[6][3] == "Cy + All"


def test_new_log_rows_skip_rows_that_only_look_empty():
    b, store = setup()
    log_ws = b.sheets[2]
    log_ws.rows.append(['=IF(FALSE,1,"")'] + [""] * 10)  # shows as blank
    task = store.load_tasks().find("X02")
    store.log(date(2026, 11, 17), None, task, "Signed off", "Ana", "Done")
    assert log_ws.rows[5][0].startswith("=IF")
    assert log_ws.rows[6][3] == "X02"


def test_check_in_never_overwrites_formulas_or_text():
    b, store = setup()
    ci = b.sheets[3]
    ci.rows[4][5] = "=JOIN()"
    assert not store.fill_checkin(1, "Done: X02", "")
    assert ci.rows[4][5] == "=JOIN()"


def test_no_columns_added_over_existing_data():
    ws = FakeWorksheet("Plan", [["Week", "Task"], ["1", "a", "side note"]])
    b = FakeBook(ws)
    SheetStore(b, Settings()).load_tasks()
    assert ws.rows[0] == ["Week", "Task"]
    assert ws.rows[1] == ["1", "a", "side note"]


def test_read_only_mode_writes_nothing_anywhere():
    b, store = setup(read_only=True)
    before = snapshot(b)
    table = store.load_tasks()
    team = store.load_team([n for t in table.tasks for n in t.assignees])
    assert [m.name for m in team] == ["Ana", "Ben", "Cy"]
    store.update_task("X02", {"status": "Done", "progress": "x"}, expected_title="Task 2")
    store.log(date(2026, 11, 17), None, table.find("X02"), "Signed off", "Ana", "Done")
    store.fill_checkin(1, "Done: X02", "Still open: X03")
    assert changed_cells(before, b) == set()
    assert [s.title for s in b.sheets] == list(before)


def test_every_write_is_a_single_cell():
    b, store = setup()
    store.load_tasks()
    store.update_task("X02", {"status": "Done", "progress": "a"})
    assert all(len(w) == 3 for w in b.sheets[1].writes)  # the fake rejects ranges
