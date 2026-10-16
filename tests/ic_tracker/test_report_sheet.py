from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from ic_tracker.analysis import summarize_by_class
from ic_tracker.report.sheet import STATS_HEADER, TAB_HEADER, build_tab
from tests.ic_tracker.builders import (make_absent, make_assignment, make_excused, make_missing, make_ungraded,
                                       make_zero)

DENVER = ZoneInfo("America/Denver")


def build(items):
    return build_tab(items, summarize_by_class(items), DENVER)


def test_header_row_has_tab_columns_then_stats_block_after_a_gap():
    tab = build([make_assignment()])
    assert tab.values[0] == TAB_HEADER + [""] + STATS_HEADER
    assert (tab.data_cols, tab.total_cols) == (11, 17)


def test_graded_row_values_and_local_due_date():
    # 05:59Z is 23:59 the previous day in Denver
    a = make_assignment(course="Math", name="HW", due=datetime(2026, 9, 8, 5, 59, tzinfo=timezone.utc),
                        score=18.0, total=20.0, percent=90.0, score_raw="18")
    row = build([a]).values[1]
    assert row[:11] == ["Math", "2026-09-07", "HW", "18/20(90%)", 18.0, 20.0, 0.9, "", "", "Graded", ""]


def test_missing_row_is_flagged_and_highlighted():
    tab = build([make_assignment(name="ok"), make_missing(name="gone", total=25.0)])
    row = tab.values[2]
    assert row[7] == "Y" and row[8] == "Y" and row[9] == "Missing"
    assert tab.highlight_rows == (2,)


def test_zero_row_is_highlighted_and_excused_absent_ungraded_are_not():
    items = [make_zero(name="z"), make_excused(name="e"), make_absent(name="a"), make_ungraded(name="u")]
    tab = build(items)
    assert tab.highlight_rows == (1,)
    by_name = {r[2]: r for r in tab.values[1:]}
    assert by_name["e"][3] == "e" and by_name["e"][9] == "Excused"
    assert by_name["a"][3] == "Ab" and by_name["a"][9] == "Absent"
    assert by_name["u"][3] == "" and by_name["u"][9] == "Not graded"
    assert by_name["z"][8] == "Y" and by_name["z"][7] == ""


def test_rubric_row_shows_level_only():
    row = build([make_assignment(score=3.0, total=None, percent=None, is_rubric=True, score_raw="3")]).values[1]
    assert row[3] == "3" and row[4] == 3.0 and row[5] == "" and row[6] == ""


def test_no_due_date_gives_blank_cell():
    assert build([make_assignment(due=None)]).values[1][1] == ""


def test_comment_prefers_comments_then_feedback():
    assert build([make_assignment(comments="c", feedback="f")]).values[1][10] == "c"
    assert build([make_assignment(feedback="f")]).values[1][10] == "f"


def test_stats_block_lists_classes_and_total_beside_data_rows():
    items = [make_missing(course="A"), make_assignment(course="A"), make_zero(course="B")]
    values = build(items).values
    assert values[1][12:17] == ["A", 2, 1, 0, 1]
    assert values[2][12:17] == ["B", 1, 0, 1, 1]
    assert values[3][12:17] == ["Total", 3, 1, 1, 2]


def test_stats_block_longer_than_data_still_written():
    items = [make_assignment(course=c) for c in ("A", "B")]  # 2 rows, 3 stats rows (A, B, Total)
    values = build(items).values
    assert len(values) == 4
    assert values[3][:11] == [""] * 11
    assert values[3][12] == "Total"
