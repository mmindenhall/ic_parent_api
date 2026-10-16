"""Google Sheets access: dated tabs and the History tab."""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Optional

from ic_tracker.analysis import HistoryRow
from ic_tracker.report.sheet import TabData

logger = logging.getLogger(__name__)

HISTORY_TITLE = "History"
HISTORY_HEADER = ["Date", "Class", "Assignments", "Missing", "Zeros", "Needs attention"]
_RED = {"red": 0.957, "green": 0.8, "blue": 0.8}


def _quote(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


_FORMULA_START = ("=", "+", "-", "@")
_NUMBER_OR_DATE_LIKE = re.compile(r"^\s*\d+(?:[./-]\d+)*\s*$")
_DUE_DATE_COLUMN = 1   # kept as an ISO string so Sheets turns it into a real date


def _as_text(value):
    """Keep free text from being read as a formula, number or date: a leading apostrophe forces text."""
    if isinstance(value, str) and value and (value.startswith(_FORMULA_START) or _NUMBER_OR_DATE_LIKE.match(value)):
        return "'" + value
    return value


def _safe_values(values: list) -> list:
    """Escape text cells of a tab for USER_ENTERED input. The header row and the due-date column are left as is."""
    return [list(row) if i == 0 else
            [cell if col == _DUE_DATE_COLUMN else _as_text(cell) for col, cell in enumerate(row)]
            for i, row in enumerate(values)]


def tab_url(spreadsheet_id: str, gid: int) -> str:
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit#gid={gid}"


def _grid(gid: int, row0: int = 0, row1: Optional[int] = None, col0: int = 0, col1: Optional[int] = None) -> dict:
    rng = {"sheetId": gid, "startRowIndex": row0, "startColumnIndex": col0}
    if row1 is not None:
        rng["endRowIndex"] = row1
    if col1 is not None:
        rng["endColumnIndex"] = col1
    return rng


def _format_requests(gid: int, tab: TabData, reset: bool) -> list:
    requests = []
    if reset:
        requests.append({"updateCells": {"range": {"sheetId": gid}, "fields": "userEnteredFormat"}})
    requests.append({"updateSheetProperties": {
        "properties": {"sheetId": gid, "gridProperties": {"frozenRowCount": 1}},
        "fields": "gridProperties.frozenRowCount"}})
    requests.append({"repeatCell": {
        "range": _grid(gid, 0, 1, 0, tab.total_cols),
        "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
        "fields": "userEnteredFormat.textFormat.bold"}})
    for row in tab.highlight_rows:
        requests.append({"repeatCell": {
            "range": _grid(gid, row, row + 1, 0, tab.data_cols),
            "cell": {"userEnteredFormat": {"backgroundColor": _RED}},
            "fields": "userEnteredFormat.backgroundColor"}})
    requests.append({"repeatCell": {
        "range": _grid(gid, 1, None, 1, 2),
        "cell": {"userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": "yyyy-mm-dd"}}},
        "fields": "userEnteredFormat.numberFormat"}})
    requests.append({"repeatCell": {
        "range": _grid(gid, 1, None, 6, 7),
        "cell": {"userEnteredFormat": {"numberFormat": {"type": "PERCENT", "pattern": "0%"}}},
        "fields": "userEnteredFormat.numberFormat"}})
    requests.append({"autoResizeDimensions": {"dimensions": {
        "sheetId": gid, "dimension": "COLUMNS", "startIndex": 0, "endIndex": tab.total_cols}}})
    return requests


class SheetsGateway:
    def __init__(self, service):
        self._svc = service

    def _tabs(self, sid: str) -> dict:
        meta = self._svc.spreadsheets().get(spreadsheetId=sid, fields="sheets.properties(sheetId,title)").execute()
        return {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta.get("sheets", [])}

    def _batch(self, sid: str, requests: list) -> dict:
        return self._svc.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": requests}).execute()

    def _add_tab(self, sid: str, title: str, index: Optional[int] = None) -> int:
        props = {"title": title}
        if index is not None:
            props["index"] = index
        reply = self._batch(sid, [{"addSheet": {"properties": props}}])
        return reply["replies"][0]["addSheet"]["properties"]["sheetId"]

    def tab_titles(self, sid: str) -> list:
        return list(self._tabs(sid))

    def write_tab(self, sid: str, title: str, tab: TabData) -> int:
        """Create the tab at the front, or clear values and formatting of an existing one, then write it."""
        tabs = self._tabs(sid)
        existing = title in tabs
        if existing:
            gid = tabs[title]
            self._svc.spreadsheets().values().clear(spreadsheetId=sid, range=_quote(title), body={}).execute()
        else:
            gid = self._add_tab(sid, title, index=0)
        self._svc.spreadsheets().values().update(
            spreadsheetId=sid, range=f"{_quote(title)}!A1", valueInputOption="USER_ENTERED",
            body={"values": _safe_values(tab.values)}).execute()
        self._batch(sid, _format_requests(gid, tab, reset=existing))
        return gid

    def read_tab_values(self, sid: str, title: str) -> list:
        resp = self._svc.spreadsheets().values().get(spreadsheetId=sid, range=f"{_quote(title)}!A:K").execute()
        return resp.get("values", [])

    def read_history(self, sid: str) -> list:
        if HISTORY_TITLE not in self._tabs(sid):
            return []
        resp = self._svc.spreadsheets().values().get(spreadsheetId=sid, range=f"{HISTORY_TITLE}!A2:F").execute()
        rows = []
        for values in resp.get("values", []):
            try:
                rows.append(HistoryRow(date.fromisoformat(str(values[0])), values[1],
                                       int(values[2]), int(values[3]), int(values[4])))
            except (ValueError, IndexError):
                logger.warning("Skipping unreadable History row: %r", values)
        return rows

    def upsert_history(self, sid: str, new_rows: list) -> None:
        """Replace every History row for the dates in new_rows; keep all other dates."""
        if HISTORY_TITLE not in self._tabs(sid):
            self._add_tab(sid, HISTORY_TITLE)
        replaced = {r.run_date for r in new_rows}
        kept = [r for r in self.read_history(sid) if r.run_date not in replaced]
        merged = sorted(kept + list(new_rows), key=lambda r: (r.run_date, r.course.casefold()))
        values = [HISTORY_HEADER] + [[r.run_date.isoformat(), r.course, r.assignments, r.missing, r.zeros,
                                      r.needs_attention] for r in merged]
        # Write first, then trim leftover rows, so a failed write never leaves History empty.
        self._svc.spreadsheets().values().update(
            spreadsheetId=sid, range=f"{HISTORY_TITLE}!A1", valueInputOption="RAW", body={"values": values}).execute()
        self._svc.spreadsheets().values().clear(
            spreadsheetId=sid, range=f"{HISTORY_TITLE}!A{len(values) + 1}:F", body={}).execute()
