from datetime import date

from taskbot.config import Settings
from taskbot.store import SheetStore

from .fakes import FakeBook, FakeWorksheet


def make(rows, **settings):
    ws = FakeWorksheet("Plan", rows)
    book = FakeBook(ws)
    return SheetStore(book, Settings(**settings)), ws, book


def test_first_load_adds_columns_and_ids():
    store, ws, _ = make([["Week", "Task"], ["1", "Literature review"], ["", "Pick module"]])
    table = store.load_tasks()
    assert ws.rows[0] == ["Week", "Task", "ID", "Owner(s)", "Status", "Completion date"]
    assert [t.id for t in table.tasks] == ["T1", "T2"]
    assert ws.rows[2][2] == "T2"
    # Second load changes nothing.
    before = [list(r) for r in ws.rows]
    store.load_tasks()
    assert ws.rows == before


def test_auto_add_off_leaves_sheet_alone():
    store, ws, _ = make([["Week", "Task"], ["1", "a"]], auto_add_columns=False)
    store.load_tasks()
    assert ws.rows[0] == ["Week", "Task"]


def test_sign_off_writes_the_right_row_and_keeps_checkboxes():
    rows = [
        ["ID", "Week", "Task", "Status", "Signed Off By", "Signed Off At", "Assigned To"],
        ["T1", "1", "a", "FALSE", "", "", "Ana"],
        ["T2", "1", "b", "", "", "", "Ben"],
    ]
    store, ws, _ = make(rows)
    store.update_task("T2", {"status": "Done", "signed_off_by": "=Ben", "signed_off_at": "x"}, "b")
    store.update_task("t1", {"status": "Done"})
    assert ws.rows[2][3:6] == ["Done", "'=Ben", "x"]
    assert ws.rows[1][3] == "TRUE"


def test_assign_many_only_fills_empty_cells():
    rows = [["ID", "Week", "Task", "Assigned To"], ["T1", "1", "a", ""], ["T2", "1", "b", "Ana"]]
    store, ws, _ = make(rows, auto_add_columns=False)
    store.assign_many({"T1": ["Ben"], "T2": ["Ben"]}, {"T1": "a", "T2": "b"})
    assert ws.rows[1][3] == "Ben" and ws.rows[2][3] == "Ana"


def test_team_tab_is_created_and_linked():
    store, _, book = make([["Week", "Task"]])
    team = store.load_team(["Ana", "Ben", "Ana"])
    assert [m.name for m in team] == ["Ana", "Ben"]
    store.link_member("ben", 42)
    store.link_member("Cy", 7)
    store.link_member("Ana", 42)  # 42 moves from Ben to Ana
    team = {m.name: m.discord_id for m in store.load_team()}
    assert team == {"Ana": 42, "Ben": None, "Cy": 7}
    assert book.sheets[1].title == "TEAM"


def test_log_creates_a_work_log_when_missing():
    store, ws, book = make([["ID", "Week", "Task"], ["T1", "1", "a"]])
    table = store.load_tasks()
    store.log(date(2026, 11, 17), date(2026, 11, 14), table.tasks[0], "Signed off", "Ana",
              "Done", "+1 note")  # fmt: skip
    log_ws = next(s for s in book.sheets if s.title == "WORK LOG")
    assert log_ws.rows[1] == [
        "2026-11-17", "2026-11-14", "Ana", "T1", "a", "Signed off", "Done", "'+1 note",
    ]  # fmt: skip
