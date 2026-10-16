"""Fetch a student's current-term assignments and normalize them."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

from ic_parent_api import InfiniteCampus

from ic_tracker.config import Settings
from ic_tracker.ic.sso import sso_login
from ic_tracker.model import (ClassGrade, NormalizedAssignment, STATUS_ABSENT, STATUS_EXCUSED, STATUS_GRADED,
                              STATUS_MISSING, STATUS_NOT_GRADED)

logger = logging.getLogger(__name__)

TERM_FINAL = "Term Final"


class StudentNotFoundError(Exception):
    """No student matches the requested first name."""


def _float(value) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        # If the datetime is naive (no timezone), attach UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        logger.warning("Could not parse datetime: %r", value)
        return None


def _status(missing: bool, score_raw: Optional[str], graded: bool) -> str:
    if missing:
        return STATUS_MISSING
    raw = (score_raw or "").strip().lower()
    if raw == "e":
        return STATUS_EXCUSED
    if raw == "ab":
        return STATUS_ABSENT
    return STATUS_GRADED if graded else STATUS_NOT_GRADED


def normalize(a) -> NormalizedAssignment:
    score = _float(a.scorepoints if a.scorepoints is not None else a.score)
    total = _float(a.totalpoints) or None
    percent = _float(a.scorepercentage)
    if percent is None and score is not None and total:
        percent = score / total * 100
    graded = score is not None
    missing = bool(a.missing)
    return NormalizedAssignment(
        id=a.objectsectionid, course=a.coursename, name=a.assignmentname,
        due=_dt(a.duedate), assigned=_dt(a.assigneddate), graded_at=_dt(a.scoremodifieddate),
        term_ids=tuple(a.termids), score=score, total=total, percent=percent, score_raw=a.score,
        status=_status(missing, a.score, graded), is_graded=graded, is_rubric=graded and total is None,
        missing=missing, late=bool(a.late), incomplete=bool(a.incomplete), turned_in=bool(a.turnedin),
        comments=a.comments, feedback=a.feedback)


def _parse_date(date_str: Optional[str]) -> Optional[date]:
    """Parse a date from 'YYYY-MM-DD' or ISO timestamp format.

    For ISO timestamps like '2026-08-19T00:00:00', extract the first 10 chars.
    Returns None if the string cannot be parsed.
    """
    if not date_str:
        return None
    try:
        # Take first 10 chars to handle ISO timestamps
        date_part = date_str[:10]
        return date.fromisoformat(date_part)
    except (ValueError, TypeError):
        return None


def find_student(students, first_name: str):
    wanted = first_name.strip().lower()
    matches = [s for s in students if wanted in (s.firstname.lower(), (s.alias or "").lower())]
    if not matches:
        names = ", ".join(s.firstname for s in students)
        raise StudentNotFoundError(f"No student named '{first_name}'. Available: {names}")
    return matches[0]


async def current_term(client, assignments, today: date):
    """The term that started most recently on or before today, across the student's schedule structures.

    Prefers a term whose [start, end] window contains today. If multiple contain today,
    picks the latest start date, breaking ties by earliest end date (narrowest span).
    If no term contains today, falls back to the term with the latest start date.
    """
    terms = []
    for structure_id in sorted({a.structureid for a in assignments}):
        terms.extend(await client.terms(structure_id))

    # Parse dates and skip terms with unparseable dates
    parsed_terms = []
    for t in terms:
        start = _parse_date(t.startdate)
        end = _parse_date(t.enddate)
        if start is None:
            logger.warning("Skipping term %s (%s): unparseable start date %r", t.termid, t.termname, t.startdate)
            continue
        if end is None:
            logger.warning("Skipping term %s (%s): unparseable end date %r", t.termid, t.termname, t.enddate)
            continue
        parsed_terms.append((t, start, end))

    # Filter to candidates (started on or before today)
    candidates = [(t, start, end) for t, start, end in parsed_terms if start <= today]

    if not candidates:
        return None

    # Separate candidates into those that contain today and those that don't
    contains_today = [(t, start, end) for t, start, end in candidates if start <= today <= end]

    if contains_today:
        # Among those containing today, prefer latest start, then earliest end (narrowest)
        return max(contains_today, key=lambda x: (x[1], -x[2].toordinal()))[0]
    else:
        # Fall back to latest start date
        return max(candidates, key=lambda x: x[1])[0]


def class_grades(enrollments, term_id: int) -> list:
    """Each class's Term Final grade for one term: the in-progress grade, else the posted grade."""
    grades = []
    for enrollment in enrollments:
        for term in enrollment.terms:
            if term.termID != term_id:
                continue
            for course in term.courses:
                if course.dropped:
                    continue
                task = next((t for t in course.gradingTasks if t.taskName == TERM_FINAL), None)
                if task is None:
                    continue
                letter = task.progressScore if task.progressScore is not None else task.score
                percent = task.progressPercent if task.progressPercent is not None else task.percent
                if letter is None and percent is None:
                    continue
                grades.append(ClassGrade(course.courseName, letter, percent))
    return grades


@dataclass(frozen=True)
class FetchResult:
    student_first_name: str
    term_name: Optional[str]
    term_start: Optional[str]
    term_end: Optional[str]
    assignments: list
    grades: list = field(default_factory=list)


async def fetch_student_data(client, first_name: str, today: date) -> FetchResult:
    student = find_student(await client.students(), first_name)
    raw_assignments = await client.assignments(student.personid)
    term = await current_term(client, raw_assignments, today)
    if term is None:
        return FetchResult(student.firstname, None, None, None, [])
    in_term = [a for a in raw_assignments if term.termid in a.termids and a.active is not False]
    try:
        grades = class_grades(await client.grades(student.personid), term.termid)
    except Exception:   # grades are an extra; the assignment report must still go out
        logger.warning("Could not fetch grades; continuing without them", exc_info=True)
        grades = []
    return FetchResult(student.firstname, term.termname, term.startdate, term.enddate,
                       [normalize(a) for a in in_term], grades)


async def fetch(settings: Settings, today: date) -> FetchResult:
    cookies = await sso_login(settings.ic_base_url, settings.ic_username, settings.ic_password)
    client = InfiniteCampus(settings.ic_base_url, settings.ic_username, settings.ic_password,
                            settings.ic_district, cookies=cookies)
    return await fetch_student_data(client, settings.student, today)
