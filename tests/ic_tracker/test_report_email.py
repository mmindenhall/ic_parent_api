from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from ic_tracker.analysis import HistoryRow, build_trend
from ic_tracker.model import ClassGrade
from ic_tracker.report.email import EmailContext, render_email, token_footer
from tests.ic_tracker.builders import make_assignment, make_missing, make_zero

TZ = ZoneInfo("America/Denver")
D = date(2026, 10, 15)


def ctx(rows=None, problems=None, days=7, **kw):
    rows = rows if rows is not None else [HistoryRow(D, "Math", 10, 2, 1)]
    problems = problems if problems is not None else [make_missing(course="Math", name="Worksheet"),
                                                      make_zero(course="Math", name="Quiz")]
    base = dict(student_name="Alex", run_date=D, trend=build_trend(rows, D), problems=problems,
                tab_url="https://docs.google.com/spreadsheets/d/S/edit#gid=5", tab_title="2026-10-15",
                token_days_remaining=days, tz=TZ)
    base.update(kw)
    return EmailContext(**base)


def test_subject_is_neutral():
    assert render_email(ctx()).subject == "Alex: assignment check-in, Thu Oct 15"


def test_summary_line_and_comparisons():
    rows = [HistoryRow(date(2026, 10, 7), "Math", 10, 9, 0), HistoryRow(date(2026, 10, 14), "Math", 10, 5, 0),
            HistoryRow(D, "Math", 10, 1, 1)]   # matches the default problems: 1 missing + 1 zero
    text = render_email(ctx(rows=rows)).text
    assert "Needs attention today: 2 (1 missing, 1 zero)." in text
    assert "Last run: 5." in text and "One week ago: 9." in text


def test_first_run_omits_comparisons_and_renders_one_column():
    content = render_email(ctx())
    assert "Last run" not in content.text and "One week ago" not in content.text
    assert content.html.count("<th") == 2  # class header + one date column


def test_grid_headers_are_compact_numeric_dates():
    rows = [HistoryRow(date(2026, 10, 8), "Math", 10, 3, 0), HistoryRow(D, "Math", 10, 1, 1)]
    content = render_email(ctx(rows=rows))
    assert ">10/8</th>" in content.html and ">10/15</th>" in content.html
    assert content.text.splitlines()[2].split()[-2:] == ["10/8", "10/15"]
    assert "overflow-x:auto" in content.html


def test_nothing_to_report_day():
    content = render_email(ctx(rows=[HistoryRow(D, "Math", 10, 0, 0)], problems=[]))
    assert "Nothing needs attention today." in content.text
    assert "Today's items" not in content.text


def test_items_grouped_by_class_with_local_due_date_and_kind():
    p = [make_missing(course="Math", name="Worksheet", due=datetime(2026, 10, 2, 5, 59, tzinfo=timezone.utc))]
    text = render_email(ctx(problems=p)).text
    assert "Math" in text and "Worksheet" in text and "Oct 1" in text and "Missing" in text


def test_link_to_tab_is_present_in_both_parts():
    c = render_email(ctx())
    assert 'href="https://docs.google.com/spreadsheets/d/S/edit#gid=5"' in c.html
    assert "https://docs.google.com/spreadsheets/d/S/edit#gid=5" in c.text
    assert "2026-10-15" in c.html


def test_html_escapes_names():
    p = [make_missing(course="A & B <i>", name='Quiz "1" <script>alert(1)</script>')]
    html = render_email(ctx(problems=p, rows=[HistoryRow(D, "A & B <i>", 3, 1, 0)])).html
    assert "<script>" not in html and "&lt;script&gt;" in html and "A &amp; B &lt;i&gt;" in html


def test_trend_grid_shows_zero_for_class_absent_today():
    rows = [HistoryRow(date(2026, 10, 14), "Art", 4, 3, 0), HistoryRow(D, "Math", 10, 1, 0)]
    text = render_email(ctx(rows=rows)).text
    art_line = next(line for line in text.splitlines() if line.startswith("Art"))
    assert art_line.split()[-2:] == ["3", "0"]


def test_no_percentages_or_red_in_email():
    html = render_email(ctx()).html.lower()
    assert "%" not in html
    for red in ("#ff0000", "red", "#f4cccc"):
        assert red not in html


def test_token_footer_variants():
    assert token_footer(None) == ("", False)
    assert token_footer(5) == ("Google sign-in expires in 5 days. Renew with: ic-tracker auth", False)
    assert token_footer(1) == ("Google sign-in expires in 1 day. Renew with: ic-tracker auth", True)
    assert token_footer(2)[1] is True and token_footer(3)[1] is False
    assert token_footer(0) == ("Google sign-in expires today. Renew with: ic-tracker auth", True)
    assert token_footer(-2) == ("Google sign-in has expired. Renew with: ic-tracker auth", True)


def test_footer_in_email_only_when_ttl_set():
    assert "ic-tracker auth" in render_email(ctx(days=3)).text
    assert "ic-tracker auth" not in render_email(ctx(days=None)).text
    assert "color:#9a6700" in render_email(ctx(days=1)).html      # emphasized when 2 days or fewer remain
    assert "color:#9a6700" not in render_email(ctx(days=5)).html


def grades_ctx(**kw):
    rows = [HistoryRow(date(2026, 10, 14), "Math", 10, 3, 0), HistoryRow(D, "Math", 10, 1, 1),
            HistoryRow(date(2026, 10, 14), "Art", 4, 0, 0), HistoryRow(D, "Art", 4, 0, 0)]
    return ctx(rows=rows, grades={"Math": ClassGrade("Math", "D", 61.75)}, **kw)


def test_todays_grades_is_the_last_column_after_the_dates():
    html = render_email(grades_ctx()).html
    assert html.index(">10/15</th>") < html.index("Today's Grades</th>")
    assert html.count("Grades</th>") == 1


def test_grade_cell_uses_letter_and_percent_and_dash_when_a_class_has_none():
    html = render_email(grades_ctx()).html
    assert "D (61.75%)" in html
    art_row = next(r for r in html.split("<tr>") if ">Art<" in r)
    assert ">-</td></tr>" in art_row


def test_totals_row_has_an_empty_grade_cell():
    html = render_email(grades_ctx()).html
    total_row = next(r for r in html.split("<tr>") if ">Total<" in r)
    assert total_row.count("<td") == 1 + 2 + 1   # label + 2 dates + empty grade cell
    assert "D (61.75%)" not in total_row


def test_text_grid_has_the_grades_column_last():
    lines = render_email(grades_ctx()).text.splitlines()
    header = next(line for line in lines if line.startswith("Class"))
    assert header.endswith("Today's Grades")
    math = next(line for line in lines if line.startswith("Math"))
    assert math.endswith("D (61.75%)")
    art = next(line for line in lines if line.startswith("Art"))
    assert art.endswith("-")


def test_no_grades_means_no_column():
    content = render_email(ctx())
    assert "Today's Grades" not in content.text and "Grades</th>" not in content.html


def test_grade_text_is_escaped_in_html():
    c = ctx(grades={"Math": ClassGrade("Math", "<b>", 1.0)})
    assert "&lt;b&gt;" in render_email(c).html and "<b> (" not in render_email(c).html


UPCOMING_DUE = datetime(2026, 10, 22, 5, 59, tzinfo=timezone.utc)   # Oct 21 local


def test_problem_item_shows_teacher_comment():
    p = [make_missing(course="Math", name="Quiz fix", comments="Redo #3 & #5 by Friday")]
    c = render_email(ctx(problems=p))
    assert "Redo #3 &amp; #5 by Friday" in c.html
    assert "Redo #3 & #5 by Friday" in c.text


def test_blank_or_missing_comment_adds_nothing():
    p = [make_missing(course="Math", name="Quiz fix", comments="  ")]
    c = render_email(ctx(problems=p))
    assert "Comment" not in c.html and "Comment" not in c.text


def test_comment_is_html_escaped():
    p = [make_missing(course="Math", name="Q", comments="<script>x</script>")]
    html = render_email(ctx(problems=p)).html
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_upcoming_item_listed_with_future_due_date_and_comment():
    up = [make_assignment(course="Math", name="Fix quiz", due=UPCOMING_DUE, comments="Due Oct 21, fix all errors")]
    c = render_email(ctx(upcoming=up))
    for out in (c.html, c.text):
        assert "Fix quiz" in out and "Due in the future" in out and "Oct 21" in out
        assert "fix all errors" in out


def test_upcoming_item_appears_under_its_class_with_problem_items():
    up = [make_assignment(course="Math", name="Fix quiz", due=UPCOMING_DUE, comments="Do it")]
    text = render_email(ctx(upcoming=up)).text
    assert text.count("\nMath\n") == 1
    assert text.index("Worksheet") < text.index("Fix quiz")


def test_upcoming_items_do_not_change_the_tally():
    up = [make_assignment(course="Math", name="Fix quiz", due=UPCOMING_DUE, comments="Do it")]
    assert "Needs attention today: 2 (1 missing, 1 zero)." in render_email(ctx(upcoming=up)).text


def test_quiet_day_still_lists_upcoming_items():
    up = [make_assignment(course="Art", name="Fix quiz", due=UPCOMING_DUE, comments="Do it")]
    c = render_email(ctx(rows=[HistoryRow(D, "Math", 10, 0, 0)], problems=[], upcoming=up))
    assert "Nothing needs attention today." in c.text
    assert "Fix quiz" in c.text and "Due in the future" in c.text


def test_teacher_comments_are_red_but_item_text_is_not():
    p = [make_missing(course="Math", name="Quiz fix", comments="Redo it")]
    html = render_email(ctx(problems=p)).html
    assert 'color:#c62828;' in html
    comment_div = next(part for part in html.split("<div") if "Teacher comment" in part)
    assert "color:#c62828" in comment_div
    assert html.count("#c62828") == 1
