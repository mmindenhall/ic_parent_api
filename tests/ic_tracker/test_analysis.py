from datetime import date, datetime, timezone

from ic_tracker.analysis import (ClassCounts, HistoryRow, KIND_MISSING, KIND_ZERO, build_trend,
                                 exclude_courses, problem_kind, sort_assignments, summarize_by_class,
                                 total_of)
from tests.ic_tracker.builders import (make_absent, make_assignment, make_excused, make_missing,
                                       make_ungraded, make_zero)


def test_problem_kind():
    assert problem_kind(make_missing()) == KIND_MISSING
    assert problem_kind(make_zero()) == KIND_ZERO
    assert problem_kind(make_assignment()) is None
    assert problem_kind(make_ungraded()) is None


def test_excused_and_absent_are_never_problems():
    assert problem_kind(make_excused()) is None
    assert problem_kind(make_absent()) is None


def test_missing_wins_over_zero_so_nothing_is_double_counted():
    counts = summarize_by_class([make_missing(), make_zero()])
    assert (counts[0].missing, counts[0].zeros, counts[0].needs_attention) == (1, 1, 2)
    assert summarize_by_class([make_missing()])[0].zeros == 0


def test_exclude_courses_prefix_case_insensitive():
    items = [make_assignment(course="Seminar 12"), make_assignment(course="seminar"), make_assignment(course="Math")]
    assert [a.course for a in exclude_courses(items, ("Seminar",))] == ["Math"]
    assert len(exclude_courses(items, ())) == 3


def test_sort_by_course_then_due_and_none_due_last():
    early = datetime(2026, 9, 1, tzinfo=timezone.utc)
    late = datetime(2026, 9, 9, tzinfo=timezone.utc)
    items = [make_assignment(course="B", due=early), make_assignment(course="A", due=late, name="z"),
             make_assignment(course="A", due=None, name="none"), make_assignment(course="A", due=early, name="e")]
    ordered = [(a.course, a.name) for a in sort_assignments(items)]
    assert ordered == [("A", "e"), ("A", "z"), ("A", "none"), ("B", "Homework")]


def test_summarize_by_class_and_total():
    counts = summarize_by_class([make_assignment(course="B"), make_missing(course="A"), make_zero(course="A"),
                                 make_assignment(course="A")])
    assert [c.course for c in counts] == ["A", "B"]
    assert counts[0] == ClassCounts("A", 3, 1, 1)
    total = total_of(counts)
    assert (total.course, total.assignments, total.needs_attention) == ("Total", 4, 2)


def _rows(d, **by_course):
    return [HistoryRow(d, c, 10, n, 0) for c, n in by_course.items()]


def test_trend_window_is_previous_seven_runs_plus_today():
    rows = []
    for day in range(1, 11):
        rows += _rows(date(2026, 10, day), Math=day)
    trend = build_trend(rows, date(2026, 10, 10))
    assert trend.dates[0] == date(2026, 10, 3) and trend.dates[-1] == date(2026, 10, 10)
    assert len(trend.dates) == 8
    assert trend.total(date(2026, 10, 10)) == 10
    assert trend.previous_total == 9


def test_trend_class_missing_on_some_dates_counts_zero():
    rows = _rows(date(2026, 10, 1), Math=2, Art=1) + _rows(date(2026, 10, 2), Math=1)
    trend = build_trend(rows, date(2026, 10, 2))
    assert trend.courses == ("Art", "Math")
    assert trend.count("Art", date(2026, 10, 2)) == 0
    assert trend.count("Art", date(2026, 10, 1)) == 1


def test_first_run_has_one_column_and_no_comparisons():
    trend = build_trend(_rows(date(2026, 10, 2), Math=3), date(2026, 10, 2))
    assert trend.dates == (date(2026, 10, 2),)
    assert trend.previous_total is None and trend.week_ago_total is None


def test_week_ago_total_uses_latest_run_on_or_before_seven_days_earlier():
    rows = _rows(date(2026, 10, 1), Math=9) + _rows(date(2026, 10, 7), Math=5) + _rows(date(2026, 10, 9), Math=4)
    # Oct 9 minus 7 days = Oct 2; the latest run on or before Oct 2 is Oct 1.
    assert build_trend(rows, date(2026, 10, 9)).week_ago_total == 9
    assert build_trend(rows, date(2026, 10, 7)).week_ago_total is None  # nothing on or before Sep 30


def test_history_row_from_counts():
    row = HistoryRow.from_counts(date(2026, 10, 2), ClassCounts("Math", 5, 2, 1))
    assert (row.run_date, row.course, row.assignments, row.needs_attention) == (date(2026, 10, 2), "Math", 5, 3)


def test_upcoming_with_comment_keeps_only_future_commented_items_sorted():
    from ic_tracker.analysis import upcoming_with_comment
    now = datetime(2026, 10, 15, 13, 0, tzinfo=timezone.utc)
    soon = datetime(2026, 10, 20, 5, 59, tzinfo=timezone.utc)
    later = datetime(2026, 10, 27, 5, 59, tzinfo=timezone.utc)
    items = [
        make_assignment(course="Math", name="B later", due=later, comments="Bring notes"),
        make_assignment(course="Math", name="A soon", due=soon, comments="Fix quiz errors"),
        make_assignment(course="Math", name="no comment", due=soon, comments=None),
        make_assignment(course="Math", name="blank comment", due=soon, comments="   "),
        make_assignment(course="Math", name="past", due=datetime(2026, 10, 1, tzinfo=timezone.utc), comments="Old"),
        make_assignment(course="Math", name="no due date", due=None, comments="Hi"),
        make_missing(course="Math", name="missing future", due=soon, comments="Turn in"),
    ]
    assert [a.name for a in upcoming_with_comment(items, now)] == ["A soon", "B later"]


def test_upcoming_with_comment_includes_excused_items():
    from ic_tracker.analysis import upcoming_with_comment
    now = datetime(2026, 10, 15, 13, 0, tzinfo=timezone.utc)
    item = make_excused(due=datetime(2026, 10, 20, tzinfo=timezone.utc), comments="Note")
    assert upcoming_with_comment([item], now) == [item]
