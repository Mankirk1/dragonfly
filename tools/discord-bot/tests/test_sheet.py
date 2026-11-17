from datetime import date

import pytest
from taskbot.config import Columns
from taskbot.sheet import (
    Member,
    SheetFormatError,
    match_member,
    next_ids,
    parse_tasks,
    parse_team,
    parse_week,
    safe_cell,
    split_names,
)

PLAN = [
    ["Dragonfly weekly plan", "", "", ""],
    ["", "", "", ""],
    ["Week", "Task", "Owner", "Status"],
    ["Week 1", "Literature review", "Dana", "Done"],
    ["", "Pick radar module", "Ana, Ben", ""],
    ["Week 2-3", "Build IF amplifier", "", "In progress"],
    ["", "", "", ""],
    ["3", "Range-FFT code", "", "FALSE"],
]


def test_finds_header_below_a_title_and_carries_merged_weeks():
    table = parse_tasks(PLAN, Columns())
    assert table.header_row == 3
    assert [t.title for t in table.tasks] == [
        "Literature review",
        "Pick radar module",
        "Build IF amplifier",
        "Range-FFT code",
    ]
    assert [t.week for t in table.tasks] == [1, 1, 2, 3]
    assert table.tasks[2].week_end == 3
    assert table.tasks[1].assignees == ["Ana", "Ben"]
    assert table.tasks[0].row == 4
    assert table.tasks[0].is_done(("done",))
    assert not table.tasks[3].is_done(("done", "true"))


def test_configured_column_names_win():
    rows = [["Wk", "What", "Done?"], ["1", "Thing", "TRUE"]]
    table = parse_tasks(rows, Columns(week="Wk", task="What", status="Done?"))
    assert table.tasks[0].status == "TRUE"
    with pytest.raises(SheetFormatError):
        parse_tasks(rows, Columns(week="Nope"))


def test_missing_columns_is_a_clear_error():
    with pytest.raises(SheetFormatError):
        parse_tasks([["Name", "Notes"], ["a", "b"]], Columns())


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("Week 4", (4, 4)),
        ("W2-3", (2, 3)),
        ("Weeks 5 to 7", (5, 7)),
        ("S6", (6, 6)),
        ("", (None, None)),
        ("TBD", (None, None)),
        ("2026-09-21", (3, 3)),
        ("21/09/2026", (3, 3)),
    ],
)
def test_parse_week(cell, expected):
    assert parse_week(cell, date(2026, 9, 7)) == expected


def test_next_ids_continue_after_the_highest():
    table = parse_tasks([["ID", "Week", "Task"], ["T4", "1", "a"], ["", "1", "b"]], Columns())
    assert next_ids(table.tasks) == {3: "T5"}


def test_team_and_name_matching():
    team = parse_team([["Name", "Discord ID"], ["Dana Lopez", "123"], ["Ana", ""]])
    assert team[0].discord_id == 123 and team[1].discord_id is None
    assert match_member("dana", team).name == "Dana Lopez"
    assert match_member("ANA", team).name == "Ana"
    assert match_member("Zed", team) is None
    two = [Member(2, "Sam A", 1), Member(3, "Sam B", 2)]
    assert match_member("Sam", two) is None  # ambiguous


def test_split_names_and_formula_guard():
    assert split_names("Ana & Ben and Cy / Di") == ["Ana", "Ben", "Cy", "Di"]
    assert safe_cell("=IMPORTXML(1)") == "'=IMPORTXML(1)"
    assert safe_cell("Dana") == "Dana"
