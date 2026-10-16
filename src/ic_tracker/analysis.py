"""Pure logic: filtering, sorting, problem classification, per-class counts, trend."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional

from ic_tracker.model import NormalizedAssignment, STATUS_GRADED

KIND_MISSING = "Missing"
KIND_ZERO = "Zero"
_LATEST = datetime.max.replace(tzinfo=timezone.utc)


def problem_kind(a: NormalizedAssignment) -> Optional[str]:
    """Missing wins over zero; excused, absent and ungraded items are never problems."""
    if a.missing:
        return KIND_MISSING
    if a.status == STATUS_GRADED and a.score == 0:
        return KIND_ZERO
    return None


def exclude_courses(assignments: Iterable[NormalizedAssignment], prefixes: Iterable[str]) -> list[NormalizedAssignment]:
    wanted = tuple(p.casefold() for p in prefixes if p)
    items = list(assignments)
    if not wanted:
        return items
    return [a for a in items if not a.course.casefold().startswith(wanted)]


def sort_assignments(assignments: Iterable[NormalizedAssignment]) -> list[NormalizedAssignment]:
    return sorted(assignments, key=lambda a: (a.course.casefold(), a.due or _LATEST, a.name.casefold()))


def has_comment(a: NormalizedAssignment) -> bool:
    return bool(a.comments and a.comments.strip())


def upcoming_with_comment(assignments: Iterable[NormalizedAssignment], now: datetime) -> list[NormalizedAssignment]:
    """Not-yet-due items carrying a teacher comment, soonest first. Problem items are listed elsewhere."""
    upcoming = [a for a in assignments if a.due and a.due > now and has_comment(a) and not problem_kind(a)]
    return sorted(upcoming, key=lambda a: (a.due, a.course.casefold(), a.name.casefold()))


@dataclass(frozen=True)
class ClassCounts:
    course: str
    assignments: int
    missing: int
    zeros: int   # graded zero and not flagged missing

    @property
    def needs_attention(self) -> int:
        return self.missing + self.zeros


def summarize_by_class(assignments: Iterable[NormalizedAssignment]) -> list[ClassCounts]:
    grouped: dict[str, list[NormalizedAssignment]] = defaultdict(list)
    for a in assignments:
        grouped[a.course].append(a)
    result = []
    for course in sorted(grouped, key=str.casefold):
        kinds = [problem_kind(a) for a in grouped[course]]
        result.append(ClassCounts(course, len(grouped[course]), kinds.count(KIND_MISSING), kinds.count(KIND_ZERO)))
    return result


def total_of(counts: Iterable[ClassCounts]) -> ClassCounts:
    counts = list(counts)
    return ClassCounts("Total", sum(c.assignments for c in counts), sum(c.missing for c in counts),
                       sum(c.zeros for c in counts))


@dataclass(frozen=True)
class HistoryRow:
    run_date: date
    course: str
    assignments: int
    missing: int
    zeros: int

    @property
    def needs_attention(self) -> int:
        return self.missing + self.zeros

    @classmethod
    def from_counts(cls, run_date: date, counts: ClassCounts) -> "HistoryRow":
        return cls(run_date, counts.course, counts.assignments, counts.missing, counts.zeros)


@dataclass(frozen=True)
class Trend:
    dates: tuple[date, ...]                 # oldest -> newest; the last is the current run
    courses: tuple[str, ...]
    totals_by_date: dict                    # every known run date <= current -> total needs attention
    _cells: dict                            # (course, date) -> needs attention

    def count(self, course: str, d: date) -> int:
        return self._cells.get((course, d), 0)

    def total(self, d: date) -> int:
        return self.totals_by_date.get(d, 0)

    @property
    def run_date(self) -> date:
        return self.dates[-1]

    @property
    def previous_total(self) -> Optional[int]:
        return self.total(self.dates[-2]) if len(self.dates) > 1 else None

    @property
    def week_ago_total(self) -> Optional[int]:
        cutoff = self.run_date - timedelta(days=7)
        candidates = [d for d in self.totals_by_date if d <= cutoff]
        return self.totals_by_date[max(candidates)] if candidates else None


def build_trend(rows: Iterable[HistoryRow], run_date: date, previous_runs: int = 7) -> Trend:
    by_date: dict[date, dict[str, int]] = defaultdict(dict)
    for r in rows:
        if r.run_date <= run_date:
            by_date[r.run_date][r.course] = by_date[r.run_date].get(r.course, 0) + r.needs_attention
    by_date.setdefault(run_date, {})
    dates = tuple(sorted(by_date)[-(previous_runs + 1):])
    courses = tuple(sorted({c for d in dates for c in by_date[d]}, key=str.casefold))
    cells = {(c, d): by_date[d].get(c, 0) for c in courses for d in dates}
    totals = {d: sum(v.values()) for d, v in by_date.items()}
    return Trend(dates, courses, totals, cells)
