"""Build the rows for a dated tab (pure; no network)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import tzinfo
from typing import Iterable

from ic_tracker.analysis import ClassCounts, problem_kind, total_of
from ic_tracker.model import NormalizedAssignment, STATUS_ABSENT, STATUS_EXCUSED

TAB_HEADER = ["Class", "Due Date", "Assignment", "Score (raw)", "Earned", "Possible", "Percent",
              "Missing", "Zero", "Status", "Comment"]
STATS_HEADER = ["Class", "Assignments", "Missing", "Zeros (not missing)", "Needs attention"]


@dataclass(frozen=True)
class TabData:
    values: list
    highlight_rows: tuple
    data_cols: int
    total_cols: int


def _score_raw(a: NormalizedAssignment) -> str:
    if a.status in (STATUS_EXCUSED, STATUS_ABSENT):
        return a.score_raw or ""
    if not a.is_graded:
        return ""
    if a.is_rubric:
        return f"{a.score:g}"
    return f"{a.score:g}/{a.total:g}({round(a.percent)}%)"


def _row(a: NormalizedAssignment, tz: tzinfo) -> list:
    return [
        a.course,
        a.due.astimezone(tz).date().isoformat() if a.due else "",
        a.name,
        _score_raw(a),
        a.score if a.is_graded else "",
        a.total if a.total is not None else "",
        a.percent / 100 if a.percent is not None else "",
        "Y" if a.missing else "",
        "Y" if a.is_graded and a.score == 0 else "",
        a.status,
        a.comments or a.feedback or "",
    ]


def build_tab(assignments: Iterable[NormalizedAssignment], counts: Iterable[ClassCounts], tz: tzinfo) -> TabData:
    assignments = list(assignments)
    counts = list(counts)
    stats = [[c.course, c.assignments, c.missing, c.zeros, c.needs_attention] for c in counts]
    total = total_of(counts)
    stats.append(["Total", total.assignments, total.missing, total.zeros, total.needs_attention])

    values = [TAB_HEADER + [""] + STATS_HEADER]
    highlight = []
    for i in range(max(len(assignments), len(stats))):
        if i < len(assignments):
            data = _row(assignments[i], tz)
            if problem_kind(assignments[i]):
                highlight.append(i + 1)
        else:
            data = [""] * len(TAB_HEADER)
        values.append(data + [""] + (stats[i] if i < len(stats) else []))
    return TabData(values, tuple(highlight), len(TAB_HEADER), len(TAB_HEADER) + 1 + len(STATS_HEADER))
