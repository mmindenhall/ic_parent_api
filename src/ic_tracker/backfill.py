"""One-time migration: convert the old xlsx and backfill History from its dated tabs."""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Optional

from ic_tracker.analysis import HistoryRow
from ic_tracker.config import Settings
from ic_tracker.google.drive import SHEET_MIME, XLSX_MIME

_DATE_TAB = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class MigrationError(Exception):
    """The tracker spreadsheet could not be found or created."""


def parse_tab_date(title: str) -> Optional[date]:
    if not _DATE_TAB.match(title):
        return None
    try:
        return date.fromisoformat(title)
    except ValueError:
        return None


def history_from_tab(run_date: date, values: list, excluded_prefixes) -> list:
    """Recompute per-class counts from the Class/Missing/Zero flag columns of an old tab.

    The stats block to the right of the data is ignored, so tabs with a different stats layout still work.
    """
    if not values or "Class" not in values[0]:
        return []
    header = values[0]
    class_i, missing_i, zero_i = header.index("Class"), header.index("Missing"), header.index("Zero")
    excluded = tuple(p.casefold() for p in excluded_prefixes if p)
    counts: dict = defaultdict(lambda: [0, 0, 0])
    for r in values[1:]:
        course = (r[class_i] if len(r) > class_i else "").strip()
        if not course or (excluded and course.casefold().startswith(excluded)):
            continue
        missing = len(r) > missing_i and r[missing_i] == "Y"
        zero = len(r) > zero_i and r[zero_i] == "Y"
        entry = counts[course]
        entry[0] += 1
        entry[1] += 1 if missing else 0
        entry[2] += 1 if zero and not missing else 0
    return [HistoryRow(run_date, course, *counts[course]) for course in sorted(counts, key=str.casefold)]


@dataclass(frozen=True)
class MigrationResult:
    spreadsheet_id: str
    converted: bool
    dates: list


def migrate(settings: Settings, drive, sheets) -> MigrationResult:
    folder = drive.find_folder(settings.drive_folder)
    sheet = drive.find_file(settings.sheet_name, folder, SHEET_MIME)
    converted = False
    if sheet is None:
        xlsx = drive.find_file(f"{settings.sheet_name}.xlsx", folder, XLSX_MIME)
        if xlsx is None:
            raise MigrationError(
                f"Neither a Google Sheet nor '{settings.sheet_name}.xlsx' found in {settings.drive_folder}")
        sheet_id = drive.convert_xlsx_to_sheet(xlsx["id"], folder, settings.sheet_name)
        converted = True
    else:
        sheet_id = sheet["id"]
    rows, dates = [], []
    for title in sheets.tab_titles(sheet_id):
        run_date = parse_tab_date(title)
        if run_date is None:
            continue
        rows.extend(history_from_tab(run_date, sheets.read_tab_values(sheet_id, title), settings.exclude_courses))
        dates.append(run_date)
    if rows:
        sheets.upsert_history(sheet_id, rows)
    return MigrationResult(sheet_id, converted, sorted(dates))
