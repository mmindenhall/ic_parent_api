from datetime import date
from zoneinfo import ZoneInfo

import pytest

from ic_tracker.config import load_settings
from ic_tracker.ic.source import FetchResult
from ic_tracker.model import ClassGrade
from ic_tracker.runner import NoDataError, prepare, run_report, write_dry_run
from tests.ic_tracker.builders import make_assignment, make_missing, make_zero

D = date(2026, 10, 15)


def settings(**env):
    base = {"IC_BASE_URL": "u", "IC_USERNAME": "u", "IC_PASSWORD": "p", "IC_DISTRICT": "d",
            "TRACKER_EMAIL_TO": "me@x.com", "TRACKER_STUDENTS": "Alex", "TRACKER_EMAIL_CC": "cc@x.com"}
    return load_settings({**base, **env})


def data(items, grades=()):
    return FetchResult("Alex", "S1", "2026-08-19", "2026-12-18", items, list(grades))


class FakeSheets:
    def __init__(self, log, fail_write=False):
        self.log, self.fail_write, self.history = log, fail_write, []

    def write_tab(self, sid, title, tab):
        self.log.append("write_tab")
        if self.fail_write:
            raise RuntimeError("sheets down")
        self.tab = (title, tab)
        return 42

    def upsert_history(self, sid, rows):
        self.log.append("upsert_history")
        self.history = list(rows)

    def read_history(self, sid):
        self.log.append("read_history")
        return self.history


class FakeGmail:
    def __init__(self, log, fail=False):
        self.log, self.fail, self.sent = log, fail, None

    def send(self, to, cc, subject, text, html):
        self.log.append("send")
        if self.fail:
            raise RuntimeError("gmail down")
        self.sent = (to, cc, subject, text, html)
        return "id"


ITEMS = [make_missing(course="Math", name="W"), make_zero(course="Math", name="Q"), make_assignment(course="Art"),
         make_assignment(course="Seminar 1")]


def go(items=ITEMS, log=None, sheets=None, gmail=None, days=5):
    log = log if log is not None else []
    sheets = sheets or FakeSheets(log)
    gmail = gmail or FakeGmail(log)
    result = run_report(settings=settings(), data=data(items), run_date=D, spreadsheet_id="S", sheets=sheets,
                        gmail=gmail, token_days_remaining=days)
    return result, sheets, gmail, log


def test_prepare_excludes_sorts_and_collects_problems():
    prep = prepare(settings(), data(ITEMS), ZoneInfo("America/Denver"))
    assert [a.course for a in prep.assignments] == ["Art", "Math", "Math"]
    assert [c.course for c in prep.counts] == ["Art", "Math"]
    assert sorted(a.name for a in prep.problems) == ["Q", "W"]


def test_order_is_sheet_then_history_then_read_then_send():
    _, _, _, log = go()
    assert log == ["write_tab", "upsert_history", "read_history", "send"]


def test_email_uses_configured_recipients_and_tab_link_and_footer():
    result, sheets, gmail, _ = go()
    to, cc, subject, text, html = gmail.sent
    assert to == ("me@x.com",) and cc == ("cc@x.com",)
    assert subject == "Alex: assignment check-in, Thu Oct 15"
    assert "gid=42" in html and "gid=42" in text and "2026-10-15" in text
    assert "expires in 5 days" in text
    assert result.tab_title == "2026-10-15" and result.needs_attention == 2
    assert sheets.tab[0] == "2026-10-15"
    assert {r.course for r in sheets.history} == {"Art", "Math"}


def test_no_assignments_aborts_before_any_write():
    log = []
    with pytest.raises(NoDataError):
        go(items=[], log=log)
    assert log == []
    with pytest.raises(NoDataError):
        go(items=[make_assignment(course="Seminar 1")], log=log)  # everything excluded
    assert log == []


def test_sheet_failure_sends_no_email():
    log = []
    with pytest.raises(RuntimeError):
        go(log=log, sheets=FakeSheets(log, fail_write=True))
    assert "send" not in log


def test_email_failure_leaves_sheet_written_and_propagates():
    log = []
    with pytest.raises(RuntimeError):
        go(log=log, gmail=FakeGmail(log, fail=True))
    assert log == ["write_tab", "upsert_history", "read_history", "send"]


def test_dry_run_writes_files_and_touches_nothing_else(tmp_path):
    paths = write_dry_run(settings=settings(), data=data(ITEMS), run_date=D, out_dir=tmp_path)
    names = sorted(p.name for p in paths)
    assert names == ["email.html", "email.txt", "tab.tsv"]
    assert "Needs attention today: 2" in (tmp_path / "email.txt").read_text()
    assert (tmp_path / "tab.tsv").read_text().startswith("Class\tDue Date")


def test_grades_appear_in_the_email_and_the_dry_run(tmp_path):
    grades = [ClassGrade("Math", "D", 61.75), ClassGrade("Seminar 1", "A", 100.0)]
    log = []
    gmail = FakeGmail(log)
    run_report(settings=settings(), data=data(ITEMS, grades), run_date=D, spreadsheet_id="S",
               sheets=FakeSheets(log), gmail=gmail, token_days_remaining=5)
    _, _, _, text, html = gmail.sent
    assert "Today's Grades" in text and "D (61.75%)" in html
    assert "Seminar" not in text and "A (100%)" not in html          # excluded course never shows
    write_dry_run(settings=settings(), data=data(ITEMS, grades), run_date=D, out_dir=tmp_path)
    assert "D (61.75%)" in (tmp_path / "email.txt").read_text()


def test_grades_never_reach_the_sheet_tab():
    log = []
    sheets = FakeSheets(log)
    run_report(settings=settings(), data=data(ITEMS, [ClassGrade("Math", "D", 61.75)]), run_date=D,
               spreadsheet_id="S", sheets=sheets, gmail=FakeGmail(log), token_days_remaining=5)
    flat = [str(cell) for row in sheets.tab[1].values for cell in row]
    assert not any("61.75" in cell or "Today's Grades" in cell for cell in flat)


def test_upcoming_commented_items_reach_the_email_but_not_the_tally():
    from datetime import datetime, timedelta, timezone
    future = datetime.now(timezone.utc) + timedelta(days=5)
    items = ITEMS + [make_assignment(course="Art", name="Fix quiz", due=future, comments="Redo it")]
    log = []
    gmail = FakeGmail(log)
    result = run_report(settings=settings(), data=data(items), run_date=D, spreadsheet_id="S",
                        sheets=FakeSheets(log), gmail=gmail, token_days_remaining=5)
    text = gmail.sent[3]
    assert "Fix quiz" in text and "Redo it" in text and result.needs_attention == 2


def test_dry_run_grid_includes_history_rows_when_given(tmp_path):
    from datetime import date as _d
    from ic_tracker.analysis import HistoryRow
    history = [HistoryRow(_d(2026, 10, 11), "Math", 5, 3, 0), HistoryRow(D, "Math", 5, 99, 0)]
    write_dry_run(settings=settings(), data=data(ITEMS), run_date=D, out_dir=tmp_path, history=history)
    text = (tmp_path / "email.txt").read_text()
    grid = next(line for line in text.splitlines() if line.startswith("Class"))
    assert grid.split()[1:3] == ["10/11", "10/15"]
    math = next(line for line in text.splitlines() if line.startswith("Math"))
    assert math.split()[1:3] == ["3", "2"]          # today's counts come from today's data, not stale history
