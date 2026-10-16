"""In-memory stand-in for the Google Sheets v4 service (the call chain the gateway uses)."""
from __future__ import annotations

import re


class _Req:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return self._fn()


class FakeSheetsService:
    def __init__(self, titles=()):
        self.tabs = {}            # title -> gid
        self.rows = {}            # title -> list of rows
        self.batches = []         # every request sent through batchUpdate, in order
        self.last_input_option = None
        self._next = 1
        for title in titles:
            self._add(title)

    def _add(self, title, index=None):
        gid = self._next
        self._next += 1
        self.tabs[title] = gid
        self.rows[title] = []
        return gid

    @staticmethod
    def _parse(range_):
        """'Title', "'T''s'!A1", 'History!A2:F' -> (title, zero-based start row)."""
        m = re.match(r"^'?(?P<t>(?:[^']|'')+?)'?(?:!(?P<c>[A-Z]+)(?P<r>\d+)?(?::[A-Z]+\d*)?)?$", range_)
        title = m.group("t").replace("''", "'")
        row = int(m.group("r")) - 1 if m.group("r") else 0
        return title, row

    def spreadsheets(self):
        return self

    def get(self, spreadsheetId, fields=None):
        return _Req(lambda: {"sheets": [{"properties": {"sheetId": g, "title": t}} for t, g in self.tabs.items()]})

    def batchUpdate(self, spreadsheetId, body):
        def run():
            replies = []
            for req in body["requests"]:
                self.batches.append(req)
                if "addSheet" in req:
                    props = req["addSheet"]["properties"]
                    gid = self._add(props["title"], props.get("index"))
                    replies.append({"addSheet": {"properties": {"sheetId": gid, "title": props["title"]}}})
                else:
                    replies.append({})
            return {"replies": replies}
        return _Req(run)

    def values(self):
        outer = self

        class _Values:
            def get(self, spreadsheetId, range):
                def run():
                    title, row = outer._parse(range)
                    return {"values": [[str(c) for c in r] for r in outer.rows[title][row:]]}
                return _Req(run)

            def update(self, spreadsheetId, range, valueInputOption, body):
                def run():
                    title, row = outer._parse(range)
                    outer.rows[title] = outer.rows[title][:row] + [list(r) for r in body["values"]]
                    outer.last_input_option = valueInputOption
                    return {}
                return _Req(run)

            def clear(self, spreadsheetId, range, body=None):
                def run():
                    title, row = outer._parse(range)
                    outer.rows[title] = outer.rows[title][:row]
                    return {}
                return _Req(run)

        return _Values()
