from datetime import date

import pytest

from ic_tracker.backfill import MigrationError, history_from_tab, migrate, parse_tab_date
from ic_tracker.config import load_settings
from ic_tracker.google.drive import SHEET_MIME, XLSX_MIME

HEADER = ["Class", "Due Date", "Assignment", "Score (raw)", "Earned", "Possible", "Percent", "Missing", "Zero",
          "Status", "Comment", "", "Class", "Assignments", "Missing", "Zeros (not missing)", "Needs attention"]


def row(course, missing="", zero="", stats=()):
    return [course, "2026-09-01", "A", "", "", "", "", missing, zero, "x", ""] + (["", *stats] if stats else [])


def test_parse_tab_date():
    assert parse_tab_date("2026-10-11") == date(2026, 10, 11)
    for bad in ("History", "2026-13-40", "Sheet1", "2026-10-1"):
        assert parse_tab_date(bad) is None


def test_history_from_tab_recomputes_counts_from_flags_not_the_stats_block():
    values = [HEADER,
              row("Math", stats=("Math", 99, 99, 99, 99)),
              row("Math", missing="Y", zero="Y"),
              row("Math", zero="Y"),
              row("Art"),
              row("Seminar 12", missing="Y", zero="Y"),
              ["", "", "", "", "", "", "", "", "", "", "", "", "Total", 5, 1, 1, 2]]
    rows = history_from_tab(date(2026, 10, 11), values, ("Seminar",))
    by = {r.course: r for r in rows}
    assert set(by) == {"Math", "Art"}
    assert (by["Math"].assignments, by["Math"].missing, by["Math"].zeros) == (3, 1, 1)
    assert (by["Art"].assignments, by["Art"].needs_attention) == (1, 0)
    assert all(r.run_date == date(2026, 10, 11) for r in rows)


def test_history_from_empty_or_headerless_tab_is_empty():
    assert history_from_tab(date(2026, 10, 11), [], ()) == []
    assert history_from_tab(date(2026, 10, 11), [["nothing", "useful"]], ()) == []


class FakeDrive:
    def __init__(self, sheet=None, xlsx=None):
        self.sheet, self.xlsx, self.converted = sheet, xlsx, []

    def find_folder(self, path):
        return "FOLDER"

    def find_file(self, name, parent, mime):
        return {SHEET_MIME: self.sheet, XLSX_MIME: self.xlsx}[mime]

    def convert_xlsx_to_sheet(self, xlsx_id, folder_id, title):
        self.converted.append((xlsx_id, folder_id, title))
        return "NEWSHEET"


class FakeSheets:
    def __init__(self, tabs):
        self.tabs, self.upserted = tabs, None

    def tab_titles(self, sid):
        return list(self.tabs)

    def read_tab_values(self, sid, title):
        return self.tabs[title]

    def upsert_history(self, sid, rows):
        self.upserted = rows


def settings():
    return load_settings({"IC_BASE_URL": "u", "IC_USERNAME": "u", "IC_PASSWORD": "p", "IC_DISTRICT": "d",
                          "TRACKER_EMAIL_TO": "a@x.com", "TRACKER_STUDENTS": "Alex"})


def test_migrate_converts_xlsx_then_backfills_dated_tabs_only():
    drive = FakeDrive(sheet=None, xlsx={"id": "XLSX"})
    sheets = FakeSheets({"2026-10-11": [HEADER, row("Math", missing="Y", zero="Y")], "History": [["x"]]})
    result = migrate(settings(), drive, sheets)
    assert result.converted and result.spreadsheet_id == "NEWSHEET"
    assert drive.converted == [("XLSX", "FOLDER", "Assignments Tracker")]
    assert result.dates == [date(2026, 10, 11)]
    assert [(r.course, r.missing) for r in sheets.upserted] == [("Math", 1)]


def test_migrate_reuses_existing_sheet_without_converting_again():
    drive = FakeDrive(sheet={"id": "EXISTING"}, xlsx={"id": "XLSX"})
    result = migrate(settings(), drive, FakeSheets({}))
    assert not result.converted and result.spreadsheet_id == "EXISTING" and drive.converted == []


def test_migrate_without_sheet_or_xlsx_is_an_error():
    with pytest.raises(MigrationError):
        migrate(settings(), FakeDrive(), FakeSheets({}))
