"""Orchestration: prepare data, write the Sheet, then send the email."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from ic_tracker.analysis import (HistoryRow, build_trend, exclude_courses, problem_kind, sort_assignments,
                                 summarize_by_class, upcoming_with_comment)
from ic_tracker.config import Settings
from ic_tracker.google.sheets import tab_url
from ic_tracker.ic.source import FetchResult
from ic_tracker.report.email import EmailContext, render_email
from ic_tracker.report.sheet import TabData, build_tab


class NoDataError(Exception):
    """Infinite Campus returned nothing to report; nothing was written."""


@dataclass(frozen=True)
class Prepared:
    assignments: list
    counts: list
    problems: list
    upcoming: list
    tab: TabData


def prepare(settings: Settings, data: FetchResult, tz, now: Optional[datetime] = None) -> Prepared:
    assignments = sort_assignments(exclude_courses(data.assignments, settings.exclude_courses))
    if not assignments:
        raise NoDataError("No assignments after filtering; refusing to overwrite today's tab with empty data.")
    counts = summarize_by_class(assignments)
    problems = [a for a in assignments if problem_kind(a)]
    upcoming = upcoming_with_comment(assignments, now or datetime.now(timezone.utc))
    return Prepared(assignments, counts, problems, upcoming, build_tab(assignments, counts, tz))


@dataclass(frozen=True)
class RunResult:
    tab_title: str
    tab_url: str
    needs_attention: int
    recipients: tuple


def run_report(*, settings: Settings, data: FetchResult, run_date: date, spreadsheet_id: str, sheets, gmail,
               token_days_remaining: Optional[int]) -> RunResult:
    """Write the dated tab, update History, then email. The Sheet is written first so the link always works."""
    tz = ZoneInfo(settings.timezone)
    prep = prepare(settings, data, tz)
    title = run_date.isoformat()
    gid = sheets.write_tab(spreadsheet_id, title, prep.tab)
    sheets.upsert_history(spreadsheet_id, [HistoryRow.from_counts(run_date, c) for c in prep.counts])
    trend = build_trend(sheets.read_history(spreadsheet_id), run_date)
    url = tab_url(spreadsheet_id, gid)
    content = render_email(EmailContext(
        student_name=data.student_first_name, run_date=run_date, trend=trend, problems=prep.problems,
        tab_url=url, tab_title=title, token_days_remaining=token_days_remaining, tz=tz,
        grades={g.course: g for g in data.grades}, upcoming=prep.upcoming))
    gmail.send(settings.email_to, settings.email_cc, content.subject, content.text, content.html)
    return RunResult(title, url, len(prep.problems), settings.email_to + settings.email_cc)


def write_dry_run(*, settings: Settings, data: FetchResult, run_date: date, out_dir: Path, history=()) -> list:
    """Render the email and tab rows to files. Today's counts come from `data`; earlier runs from `history`."""
    tz = ZoneInfo(settings.timezone)
    prep = prepare(settings, data, tz)
    earlier = [r for r in history if r.run_date != run_date]
    trend = build_trend(earlier + [HistoryRow.from_counts(run_date, c) for c in prep.counts], run_date)
    content = render_email(EmailContext(
        student_name=data.student_first_name, run_date=run_date, trend=trend, problems=prep.problems,
        tab_url="https://docs.google.com/spreadsheets/d/DRY_RUN/edit#gid=0", tab_title=run_date.isoformat(),
        token_days_remaining=settings.token_ttl_days, tz=tz, grades={g.course: g for g in data.grades},
        upcoming=prep.upcoming))
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {"email.html": content.html, "email.txt": content.text,
             "tab.tsv": "\n".join("\t".join(str(c) for c in row) for row in prep.tab.values) + "\n"}
    paths = []
    for name, text in files.items():
        path = out_dir / name
        path.write_text(text)
        paths.append(path)
    return paths
