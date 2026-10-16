import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace as NS

import pytest

from ic_tracker.ic.source import StudentNotFoundError, class_grades, current_term, fetch_student_data, find_student, normalize, _dt
from ic_tracker.model import ClassGrade
from ic_tracker.model import STATUS_ABSENT, STATUS_EXCUSED, STATUS_GRADED, STATUS_MISSING, STATUS_NOT_GRADED


def raw(**kw):
    base = dict(objectsectionid=1, coursename="Math", assignmentname="HW", duedate="2026-09-07T05:59:00.000Z",
                assigneddate="2026-09-06T06:00:00.000Z", scoremodifieddate="2026-10-13T14:34:00.000Z",
                termids=[10], comments=None, feedback=None, missing=False, late=False, incomplete=False,
                turnedin=True, score=None, scorepoints=None, scorepercentage=None, totalpoints=None,
                active=True, structureid=100)
    base.update(kw)
    return NS(**base)


def test_point_score_is_parsed():
    n = normalize(raw(score="2", scorepoints="2.0", scorepercentage="40.0", totalpoints=5))
    assert (n.score, n.total, n.percent, n.status, n.is_graded, n.is_rubric) == (2.0, 5.0, 40.0, STATUS_GRADED, True, False)
    assert n.due.isoformat() == "2026-09-07T05:59:00+00:00"
    assert n.term_ids == (10,)


def test_rubric_score_has_no_total_or_percent():
    n = normalize(raw(score="3", scorepoints="3.0"))
    assert (n.percent, n.is_rubric, n.status) == (None, True, STATUS_GRADED)


def test_missing_item_has_null_score_but_zero_points():
    n = normalize(raw(score=None, scorepoints="0.0", totalpoints=25, missing=True))
    assert (n.status, n.score, n.is_graded, n.missing) == (STATUS_MISSING, 0.0, True, True)


def test_excused_and_absent_are_not_graded():
    e = normalize(raw(score="e", totalpoints=25))
    a = normalize(raw(score="Ab", totalpoints=5))
    assert (e.status, e.is_graded, e.score) == (STATUS_EXCUSED, False, None)
    assert (a.status, a.is_graded, a.score) == (STATUS_ABSENT, False, None)


def test_ungraded_and_null_flags():
    n = normalize(raw(missing=None, late=None, incomplete=None, turnedin=None))
    assert (n.status, n.is_graded, n.missing, n.late, n.turned_in) == (STATUS_NOT_GRADED, False, False, False, False)


def test_missing_due_date_is_none():
    assert normalize(raw(duedate=None)).due is None


def test_dt_handles_z_suffix():
    result = _dt("2026-09-07T05:59:00.000Z")
    assert result == datetime(2026, 9, 7, 5, 59, 0, tzinfo=timezone.utc)


def test_dt_handles_naive_timestamp_as_utc():
    result = _dt("2026-10-15T05:59:00")
    assert result == datetime(2026, 10, 15, 5, 59, 0, tzinfo=timezone.utc)
    assert result.tzinfo is not None


def test_dt_handles_garbage_input_returns_none(caplog):
    result = _dt("not a date")
    assert result is None
    assert "not a date" in caplog.text.lower()


def test_dt_handles_empty_string():
    assert _dt("") is None


def test_dt_handles_none():
    assert _dt(None) is None


class FakeClient:
    def __init__(self, students, assignments, terms, grades=None, grades_error=None):
        self._s, self._a, self._t, self._g, self._ge = students, assignments, terms, grades or [], grades_error

    async def students(self):
        return self._s

    async def assignments(self, person_id):
        return self._a[person_id]

    async def terms(self, structure_id):
        return self._t[structure_id]

    async def grades(self, person_id):
        if self._ge:
            raise self._ge
        return self._g


def student(first, pid):
    return NS(firstname=first, lastname="M", alias=None, personid=pid)


def term(tid, name, start, end):
    return NS(termid=tid, termname=name, startdate=start, enddate=end)


def test_find_student_is_case_insensitive_and_lists_names_on_miss():
    students = [student("Alex", 1), student("Sam", 2)]
    assert find_student(students, "ALEX").personid == 1
    with pytest.raises(StudentNotFoundError) as err:
        find_student(students, "bob")
    assert "Alex" in str(err.value) and "Sam" in str(err.value)


def test_fetch_picks_current_term_and_filters_inactive():
    client = FakeClient(
        [student("Alex", 1)],
        {1: [raw(objectsectionid=1, termids=[20]), raw(objectsectionid=2, termids=[10]),
             raw(objectsectionid=3, termids=[20], active=False)]},
        {100: [term(10, "S1", "2026-08-19", "2026-12-18"), term(20, "S2", "2027-01-06", "2027-05-27")]})
    result = asyncio.run(fetch_student_data(client, "alex", date(2026, 10, 14)))
    assert result.term_name == "S1"
    assert [a.id for a in result.assignments] == [2]
    assert result.student_first_name == "Alex"


def test_fetch_with_no_started_term_returns_no_term():
    client = FakeClient([student("Alex", 1)], {1: [raw()]}, {100: [term(10, "S1", "2026-08-19", "2026-12-18")]})
    result = asyncio.run(fetch_student_data(client, "alex", date(2026, 1, 1)))
    assert result.term_name is None and result.assignments == []


def gtask(name, **kw):
    base = dict(taskName=name, score=None, percent=None, progressScore=None, progressPercent=None)
    base.update(kw)
    return NS(**base)


def gcourse(name, tasks, dropped=False):
    return NS(courseName=name, dropped=dropped, gradingTasks=tasks)


def genrollment(term_id, courses):
    return NS(terms=[NS(termID=term_id, courses=courses)])


def test_class_grades_use_the_in_progress_term_final_for_the_current_term_only():
    enrollments = [
        genrollment(10, [gcourse("AP English", [gtask("1st 6 Weeks", score="D", percent=62.5),
                                                gtask("Term Final", progressScore="B", progressPercent=85.94)])]),
        genrollment(99, [gcourse("Old Class", [gtask("Term Final", progressScore="A", progressPercent=99.0)])]),
    ]
    assert class_grades(enrollments, 10) == [ClassGrade("AP English", "B", 85.94)]


def test_class_grades_fall_back_to_the_posted_score_after_the_term_closes():
    enrollments = [genrollment(10, [gcourse("Math", [gtask("Term Final", score="C", percent=72.0)])])]
    assert class_grades(enrollments, 10) == [ClassGrade("Math", "C", 72.0)]


def test_class_grades_skip_dropped_courses_missing_term_final_and_empty_values():
    enrollments = [genrollment(10, [
        gcourse("Dropped", [gtask("Term Final", progressScore="A", progressPercent=90.0)], dropped=True),
        gcourse("No final", [gtask("1st 6 Weeks", score="A", percent=95.0)]),
        gcourse("Free Period", [gtask("Term Final")]),
        gcourse("Kept", [gtask("Term Final", progressScore="F", progressPercent=28.02)])])]
    assert class_grades(enrollments, 10) == [ClassGrade("Kept", "F", 28.02)]


def _grade_client(**kw):
    return FakeClient([student("Alex", 1)], {1: [raw(termids=[10])]},
                      {100: [term(10, "S1", "2026-08-19", "2026-12-18")]}, **kw)


def test_fetch_includes_current_term_grades():
    grades = [genrollment(10, [gcourse("Math", [gtask("Term Final", progressScore="D", progressPercent=61.75)])])]
    result = asyncio.run(fetch_student_data(_grade_client(grades=grades), "alex", date(2026, 10, 14)))
    assert result.grades == [ClassGrade("Math", "D", 61.75)]


def test_grade_failure_does_not_block_the_report():
    client = _grade_client(grades_error=RuntimeError("grades endpoint down"))
    result = asyncio.run(fetch_student_data(client, "alex", date(2026, 10, 14)))
    assert result.grades == [] and len(result.assignments) == 1


def test_current_term_with_timestamp_formatted_start_date():
    """Timestamp-formatted start dates work on the start day."""
    client = FakeClient([], {}, {100: [term(10, "S1", "2026-08-19T00:00:00", "2026-12-18")]})
    result = asyncio.run(current_term(client, [raw(structureid=100)], date(2026, 8, 19)))
    assert result.termid == 10


def test_current_term_prefers_narrowest_span_for_same_start_date():
    """Year term and semester term with same start date -> semester (narrowest) chosen."""
    client = FakeClient(
        [],
        {},
        {100: [
            term(10, "Full Year", "2026-08-19", "2027-05-27"),  # wider
            term(20, "S1", "2026-08-19", "2026-12-18"),  # narrower
        ]}
    )
    result = asyncio.run(current_term(client, [raw(structureid=100)], date(2026, 10, 14)))
    assert result.termid == 20


def test_current_term_in_break_between_terms_falls_back_to_latest_start():
    """Terms S1 (Aug-Dec) and S2 (Jan-May), today in Dec-Jan break -> S1."""
    client = FakeClient(
        [],
        {},
        {100: [
            term(10, "S1", "2026-08-19", "2026-12-18"),
            term(20, "S2", "2027-01-06", "2027-05-27"),
        ]}
    )
    result = asyncio.run(current_term(client, [raw(structureid=100)], date(2026, 12, 20)))
    assert result.termid == 10


def test_current_term_prefers_containing_window():
    """Today inside S2 -> S2."""
    client = FakeClient(
        [],
        {},
        {100: [
            term(10, "S1", "2026-08-19", "2026-12-18"),
            term(20, "S2", "2027-01-06", "2027-05-27"),
        ]}
    )
    result = asyncio.run(current_term(client, [raw(structureid=100)], date(2027, 2, 15)))
    assert result.termid == 20


def test_current_term_ignores_unparseable_date(caplog):
    """Unparseable-date term is ignored."""
    client = FakeClient(
        [],
        {},
        {100: [
            term(10, "Bad Term", "invalid-date", "2026-12-18"),
            term(20, "S1", "2026-08-19", "2026-12-18"),
        ]}
    )
    result = asyncio.run(current_term(client, [raw(structureid=100)], date(2026, 10, 14)))
    assert result.termid == 20
