from __future__ import annotations

import itertools
from dataclasses import replace
from datetime import datetime, timezone

from ic_tracker.model import (NormalizedAssignment, STATUS_ABSENT, STATUS_EXCUSED, STATUS_GRADED,
                              STATUS_MISSING, STATUS_NOT_GRADED)

_ids = itertools.count(1)


def make_assignment(**overrides) -> NormalizedAssignment:
    base = NormalizedAssignment(
        id=next(_ids), course="Math", name="Homework",
        due=datetime(2026, 9, 1, 5, 59, tzinfo=timezone.utc), assigned=None, graded_at=None,
        term_ids=(1,), score=5.0, total=5.0, percent=100.0, score_raw="5", status=STATUS_GRADED,
        is_graded=True, is_rubric=False, missing=False, late=False, incomplete=False,
        turned_in=True, comments=None, feedback=None)
    return replace(base, **overrides)


def make_missing(**overrides):
    return make_assignment(**{"score": 0.0, "percent": 0.0, "score_raw": None, "status": STATUS_MISSING,
                              "missing": True, "turned_in": False, **overrides})


def make_zero(**overrides):
    return make_assignment(**{"score": 0.0, "percent": 0.0, "score_raw": "0", **overrides})


def make_excused(**overrides):
    return make_assignment(**{"score": None, "total": 25.0, "percent": None, "score_raw": "e",
                              "status": STATUS_EXCUSED, "is_graded": False, **overrides})


def make_absent(**overrides):
    return make_excused(**{"score_raw": "Ab", "status": STATUS_ABSENT, **overrides})


def make_ungraded(**overrides):
    return make_assignment(**{"score": None, "percent": None, "score_raw": None,
                              "status": STATUS_NOT_GRADED, "is_graded": False, **overrides})
