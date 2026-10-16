"""Fetch a student's current-term assignments and normalize them."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
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
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


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


def find_student(students, first_name: str):
    wanted = first_name.strip().lower()
    matches = [s for s in students if wanted in (s.firstname.lower(), (s.alias or "").lower())]
    if not matches:
        names = ", ".join(s.firstname for s in students)
        raise StudentNotFoundError(f"No student named '{first_name}'. Available: {names}")
    return matches[0]


async def current_term(client, assignments, today: date):
    """The term that started most recently on or before today, across the student's schedule structures."""
    today_iso = today.isoformat()
    terms = []
    for structure_id in sorted({a.structureid for a in assignments}):
        terms.extend(await client.terms(structure_id))
    started = [t for t in terms if t.startdate <= today_iso]
    return max(started, key=lambda t: t.startdate, default=None)


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
