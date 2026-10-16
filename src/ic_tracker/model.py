"""Normalized assignment: parsed types, explicit grading state."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

STATUS_MISSING = "Missing"
STATUS_EXCUSED = "Excused"
STATUS_ABSENT = "Absent"
STATUS_GRADED = "Graded"
STATUS_NOT_GRADED = "Not graded"


@dataclass(frozen=True)
class NormalizedAssignment:
    id: int
    course: str
    name: str
    due: Optional[datetime]
    assigned: Optional[datetime]
    graded_at: Optional[datetime]
    term_ids: tuple[int, ...]
    score: Optional[float]       # points earned or rubric level; None when not graded/excused/absent
    total: Optional[float]       # points possible; None for rubric-style items
    percent: Optional[float]     # 0-100
    score_raw: Optional[str]     # the API's `score` string, e.g. '2', 'e', 'Ab'
    status: str                  # one of the STATUS_* constants
    is_graded: bool
    is_rubric: bool
    missing: bool
    late: bool
    incomplete: bool
    turned_in: bool
    comments: Optional[str]
    feedback: Optional[str]

    @property
    def score_display(self) -> str:
        if not self.is_graded:
            return "-"
        score = f"{self.score:g}"
        return score if self.total is None else f"{score}/{self.total:g}"


_LETTER_GRADE = re.compile(r"^[A-F][+-]?$")


@dataclass(frozen=True)
class ClassGrade:
    """A class's grade for the current term as the portal shows it, e.g. 'D' and 61.75."""
    course: str
    letter: Optional[str]
    percent: Optional[float]

    @property
    def display(self) -> str:
        """'D (61.75%)'. Rubric levels and pass marks ('3', 'P') show the number without a percent sign."""
        if self.letter is None and self.percent is None:
            return "-"
        if self.percent is None:
            return self.letter
        number = f"{self.percent:g}"
        if self.letter is None:
            return f"{number}%"
        suffix = "%" if _LETTER_GRADE.match(self.letter) else ""
        return f"{self.letter} ({number}{suffix})"
