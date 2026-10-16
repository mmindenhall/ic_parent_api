"""Render the daily email (pure; no network)."""
from __future__ import annotations

import html as _html
from dataclasses import dataclass, field
from datetime import date, tzinfo
from typing import Optional

from ic_tracker.analysis import KIND_MISSING, KIND_ZERO, Trend, has_comment, problem_kind
from ic_tracker.model import NormalizedAssignment

_ACCENT = "70,110,180"
_TODAY_BORDER = "border-left:2px solid #466eb4;border-right:2px solid #466eb4;"
_COMMENT_COLOR = "color:#c62828;"
_GRADES_HEADER = "Today's Grades"
_GRADE_CELL = "padding:4px 2px 4px 6px;text-align:center;border-left:1px solid #999;"


@dataclass(frozen=True)
class EmailContext:
    student_name: str
    run_date: date
    trend: Trend
    problems: list
    tab_url: str
    tab_title: str
    token_days_remaining: Optional[int]
    tz: tzinfo
    grades: dict = field(default_factory=dict)   # course name -> ClassGrade; empty hides the grades column
    upcoming: list = field(default_factory=list)  # not-yet-due items with a teacher comment


@dataclass(frozen=True)
class EmailContent:
    subject: str
    html: str
    text: str


def _fmt(d: date) -> str:
    return f"{d:%b} {d.day}"


def _short(d: date) -> str:
    """Compact column label (10/8) so an 8-run grid fits a phone screen."""
    return f"{d.month}/{d.day}"


def _zeros(n: int) -> str:
    return f"{n} zero" if n == 1 else f"{n} zeros"


def token_footer(days: Optional[int]) -> tuple:
    """(text, emphasized) for the Google sign-in expiry reminder; empty text when no TTL is configured."""
    if days is None:
        return "", False
    if days < 0:
        return "Google sign-in has expired. Renew with: ic-tracker auth", True
    if days == 0:
        return "Google sign-in expires today. Renew with: ic-tracker auth", True
    unit = "day" if days == 1 else "days"
    return f"Google sign-in expires in {days} {unit}. Renew with: ic-tracker auth", days <= 2


def _summary(missing: int, zeros: int, trend: Trend) -> str:
    total = missing + zeros
    parts = ["Nothing needs attention today." if total == 0
             else f"Needs attention today: {total} ({missing} missing, {_zeros(zeros)})."]
    if trend.previous_total is not None:
        parts.append(f"Last run: {trend.previous_total}.")
    if trend.week_ago_total is not None:
        parts.append(f"One week ago: {trend.week_ago_total}.")
    return " ".join(parts)


def _shade(value: int, biggest: int) -> str:
    if value <= 0 or biggest <= 0:
        return "transparent"
    return f"rgba({_ACCENT},{0.12 + 0.5 * value / biggest:.2f})"


def _grid_html(trend: Trend, grades: dict) -> str:
    biggest = max([trend.count(c, d) for c in trend.courses for d in trend.dates] + [0])
    cell = "padding:4px 2px;text-align:center;"
    head = "".join(
        f'<th style="{cell}font-weight:600;white-space:nowrap;{_TODAY_BORDER if d == trend.run_date else ""}">'
        f"{_short(d)}</th>" for d in trend.dates)
    if grades:
        head += f'<th style="{_GRADE_CELL}font-weight:600;">{_GRADES_HEADER}</th>'
    rows = []
    for course in trend.courses:
        cells = "".join(
            f'<td style="{cell}background:{_shade(trend.count(course, d), biggest)};'
            f'{_TODAY_BORDER + "font-weight:600;" if d == trend.run_date else ""}">{trend.count(course, d)}</td>'
            for d in trend.dates)
        if grades:
            grade = grades.get(course)
            cells += f'<td style="{_GRADE_CELL}">{_html.escape(grade.display if grade else "-")}</td>'
        rows.append(f'<tr><td style="padding:4px 4px 4px 0;max-width:85px;">{_html.escape(course)}</td>{cells}</tr>')
    totals = "".join(
        f'<td style="{cell}font-weight:700;border-top:1px solid #999;'
        f'{_TODAY_BORDER if d == trend.run_date else ""}">{trend.total(d)}</td>' for d in trend.dates)
    if grades:
        totals += f'<td style="{_GRADE_CELL}border-top:1px solid #999;"></td>'
    rows.append(f'<tr><td style="padding:4px 8px 4px 0;font-weight:700;border-top:1px solid #999;">Total</td>{totals}</tr>')
    return ('<div style="overflow-x:auto;"><table role="presentation" style="border-collapse:collapse;font-size:11px;">'
            f'<tr><th style="padding:4px 8px 4px 0;text-align:left;">Class</th>{head}</tr>{"".join(rows)}</table></div>')


def _grid_text(trend: Trend, grades: dict) -> str:
    labels = [_short(d) for d in trend.dates]
    name_w = max([len(c) for c in trend.courses] + [len("Class"), len("Total")])
    widths = [max(len(label), 3) + 2 for label in labels]
    lines = ["Class".ljust(name_w) + "".join(label.rjust(w) for label, w in zip(labels, widths))
             + (f"  {_GRADES_HEADER}" if grades else "")]
    for course in trend.courses:
        grade = grades.get(course) if grades else None
        lines.append(course.ljust(name_w) + "".join(str(trend.count(course, d)).rjust(w)
                                                    for d, w in zip(trend.dates, widths))
                     + (f"  {grade.display if grade else '-'}" if grades else ""))
    lines.append("Total".ljust(name_w) + "".join(str(trend.total(d)).rjust(w) for d, w in zip(trend.dates, widths)))
    return "\n".join(lines)


def _group(problems) -> list:
    grouped: dict = {}
    for a in problems:
        grouped.setdefault(a.course, []).append(a)
    return list(grouped.items())


def _groups(problems, upcoming) -> list:
    """Per class: problem items first, then upcoming commented items."""
    grouped = dict(_group(problems))
    for a in upcoming:
        grouped.setdefault(a.course, []).append(a)
    return sorted(grouped.items(), key=lambda kv: kv[0].casefold())


def _due(a: NormalizedAssignment, tz: tzinfo) -> str:
    return _fmt(a.due.astimezone(tz).date()) if a.due else "no due date"


def render_email(ctx: EmailContext) -> EmailContent:
    kinds = [problem_kind(a) for a in ctx.problems]
    summary = _summary(kinds.count(KIND_MISSING), kinds.count(KIND_ZERO), ctx.trend)
    subject = f"{ctx.student_name}: assignment check-in, {ctx.run_date:%a %b} {ctx.run_date.day}"
    footer_text, emphasized = token_footer(ctx.token_days_remaining)
    groups = _groups(ctx.problems, ctx.upcoming)

    items_html = ""
    items_text = ""
    if groups:
        items_html = '<h3 style="margin:20px 0 4px;">Today\'s items</h3>'
        items_text = "\nToday's items\n"
        for course, items in groups:
            items_html += (f'<p style="margin:12px 0 4px;font-weight:600;">{_html.escape(course)}</p>'
                           '<ul style="margin:0;padding-left:20px;">')
            items_text += f"\n{course}\n"
            for a in items:
                label = problem_kind(a) or f"Due in the future: {_due(a, ctx.tz)}"
                due = "" if not problem_kind(a) else f" &mdash; due {_html.escape(_due(a, ctx.tz))}"
                items_html += f"<li>{_html.escape(a.name)}{due} &mdash; <b>{_html.escape(label)}</b>"
                items_text += f"  - {a.name}{'' if not problem_kind(a) else f' - due {_due(a, ctx.tz)}'} - {label}\n"
                if has_comment(a):
                    comment = a.comments.strip()
                    items_html += (f'<div style="margin:2px 0 6px;font-size:13px;{_COMMENT_COLOR}">'
                                   f"Teacher comment: {_html.escape(comment)}</div>")
                    items_text += f"      Teacher comment: {comment}\n"
                items_html += "</li>"
            items_html += "</ul>"

    footer_style = "margin-top:24px;font-size:12px;" + (
        "font-weight:700;color:#9a6700;" if emphasized else "opacity:0.7;")
    footer_html = f'<p style="{footer_style}">{_html.escape(footer_text)}</p>' if footer_text else ""

    html = (
        '<!doctype html><html><head><meta charset="utf-8"><meta name="color-scheme" content="light dark"></head>'
        '<body style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;font-size:15px;line-height:1.4;">'
        f'<p style="margin:0 0 16px;">{_html.escape(summary)}</p>'
        f"{_grid_html(ctx.trend, ctx.grades)}{items_html}"
        f'<p style="margin:24px 0;"><a href="{_html.escape(ctx.tab_url, quote=True)}" '
        'style="display:inline-block;padding:10px 16px;background:#466eb4;color:#ffffff;text-decoration:none;'
        f'border-radius:6px;">Open the full list (tab {_html.escape(ctx.tab_title)})</a></p>'
        f'<p style="font-size:12px;opacity:0.7;">Data from Infinite Campus, run {ctx.run_date.isoformat()}.</p>'
        f"{footer_html}</body></html>")

    text = (f"{summary}\n\n{_grid_text(ctx.trend, ctx.grades)}\n{items_text}\n"
            f"Full list (tab {ctx.tab_title}): {ctx.tab_url}\n\n"
            f"Data from Infinite Campus, run {ctx.run_date.isoformat()}.\n"
            + (f"{footer_text}\n" if footer_text else ""))
    return EmailContent(subject, html, text)
