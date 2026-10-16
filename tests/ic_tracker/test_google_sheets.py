from datetime import date

from ic_tracker.analysis import HistoryRow
from ic_tracker.google.sheets import HISTORY_HEADER, HISTORY_TITLE, SheetsGateway, tab_url
from ic_tracker.report.sheet import TabData
from tests.ic_tracker.fakes import FakeSheetsService

TAB = TabData(values=[["Class", "x"], ["Math", 1], ["Math", 2]], highlight_rows=(2,), data_cols=2, total_cols=2)


def test_tab_url():
    assert tab_url("SID", 7) == "https://docs.google.com/spreadsheets/d/SID/edit#gid=7"


def test_write_tab_creates_front_tab_and_formats():
    svc = FakeSheetsService(["2026-10-14"])
    gw = SheetsGateway(svc)
    gid = gw.write_tab("S", "2026-10-15", TAB)
    assert svc.tabs["2026-10-15"] == gid
    assert svc.rows["2026-10-15"] == TAB.values
    add = next(r for r in svc.batches if "addSheet" in r)
    assert add["addSheet"]["properties"]["index"] == 0
    fills = [r for r in svc.batches if "repeatCell" in r
             and "backgroundColor" in r["repeatCell"]["cell"]["userEnteredFormat"]]
    assert len(fills) == 1 and fills[0]["repeatCell"]["range"]["startRowIndex"] == 2
    assert any("updateSheetProperties" in r for r in svc.batches)


def test_rewrite_same_date_clears_old_values_and_formatting():
    svc = FakeSheetsService()
    gw = SheetsGateway(svc)
    gid = gw.write_tab("S", "2026-10-15", TabData([["h"], ["a"], ["b"], ["c"]], (1, 2, 3), 1, 1))
    svc.batches.clear()
    gid2 = gw.write_tab("S", "2026-10-15", TAB)
    assert gid2 == gid
    assert svc.rows["2026-10-15"] == TAB.values  # old longer content gone
    assert svc.batches[0] == {"updateCells": {"range": {"sheetId": gid}, "fields": "userEnteredFormat"}}
    assert not any("addSheet" in r for r in svc.batches)
    fills = [r for r in svc.batches if "repeatCell" in r
             and "backgroundColor" in r["repeatCell"]["cell"]["userEnteredFormat"]]
    assert len(fills) == 1  # only the new highlight, not the three old ones


def test_tab_titles_with_apostrophe_are_quoted():
    svc = FakeSheetsService()
    gw = SheetsGateway(svc)
    gw.write_tab("S", "Kai's tab", TAB)
    assert svc.rows["Kai's tab"] == TAB.values


def test_history_roundtrip_and_upsert_replaces_same_date():
    svc = FakeSheetsService()
    gw = SheetsGateway(svc)
    d1, d2 = date(2026, 10, 14), date(2026, 10, 15)
    gw.upsert_history("S", [HistoryRow(d1, "Math", 10, 3, 1), HistoryRow(d1, "Art", 4, 0, 0)])
    gw.upsert_history("S", [HistoryRow(d2, "Math", 10, 5, 0)])
    gw.upsert_history("S", [HistoryRow(d2, "Math", 10, 2, 0)])  # same-day rerun
    rows = gw.read_history("S")
    assert [(r.run_date, r.course, r.needs_attention) for r in rows] == [
        (d1, "Art", 0), (d1, "Math", 4), (d2, "Math", 2)]
    assert svc.rows[HISTORY_TITLE][0] == HISTORY_HEADER
    assert svc.last_input_option == "RAW"


def test_read_history_without_tab_is_empty():
    assert SheetsGateway(FakeSheetsService()).read_history("S") == []


def test_read_history_skips_corrupt_rows():
    svc = FakeSheetsService([HISTORY_TITLE])
    svc.rows[HISTORY_TITLE] = [HISTORY_HEADER, ["not-a-date", "Math", 1, 1, 0, 1], ["2026-10-15", "Math", 5, 1, 0, 1]]
    assert [r.run_date for r in SheetsGateway(svc).read_history("S")] == [date(2026, 10, 15)]


def test_read_tab_values_and_titles():
    svc = FakeSheetsService(["2026-10-11"])
    svc.rows["2026-10-11"] = [["Class"], ["Math"]]
    gw = SheetsGateway(svc)
    assert gw.tab_titles("S") == ["2026-10-11"]
    assert gw.read_tab_values("S", "2026-10-11") == [["Class"], ["Math"]]


# --- History must survive a failed write ---

class _FailingUpdate(FakeSheetsService):
    """Raises on values().update for one tab, after real clear/get behaviour."""
    def __init__(self, fail_on):
        super().__init__()
        self.fail_on = fail_on

    def values(self):
        inner = super().values()
        outer = self

        class _V:
            def get(self, **kw):
                return inner.get(**kw)

            def clear(self, **kw):
                return inner.clear(**kw)

            def update(self, **kw):
                if outer.fail_on in kw["range"]:
                    raise RuntimeError("sheets down")
                return inner.update(**kw)
        return _V()


def test_failed_history_write_keeps_previous_history():
    svc = FakeSheetsService()
    gw = SheetsGateway(svc)
    d1, d2 = date(2026, 10, 14), date(2026, 10, 15)
    gw.upsert_history("S", [HistoryRow(d1, "Math", 10, 3, 1)])
    before = [list(r) for r in svc.rows[HISTORY_TITLE]]
    svc.fail_on = "History"
    failing = _FailingUpdate("History")
    failing.tabs, failing.rows, failing._next = svc.tabs, svc.rows, svc._next
    try:
        SheetsGateway(failing).upsert_history("S", [HistoryRow(d2, "Math", 10, 5, 0)])
    except RuntimeError:
        pass
    assert svc.rows[HISTORY_TITLE] == before


def test_upsert_history_trims_rows_left_over_from_a_longer_tab():
    svc = FakeSheetsService([HISTORY_TITLE])
    svc.rows[HISTORY_TITLE] = [HISTORY_HEADER] + [["2026-10-15", f"Old{i}", 1, 0, 0, 0] for i in range(5)]
    SheetsGateway(svc).upsert_history("S", [HistoryRow(date(2026, 10, 15), "Math", 10, 2, 0)])
    assert svc.rows[HISTORY_TITLE] == [HISTORY_HEADER, ["2026-10-15", "Math", 10, 2, 0, 2]]


# --- free text must not be interpreted as formulas, numbers or dates ---

def _written(values):
    svc = FakeSheetsService()
    SheetsGateway(svc).write_tab("S", "2026-10-15", TabData(values, (), 11, 11))
    return svc.rows["2026-10-15"]


def test_formula_like_and_number_like_text_is_kept_as_text():
    header = ["Class", "Due Date", "Assignment", "Score (raw)", "Earned", "Possible", "Percent", "Missing", "Zero",
              "Status", "Comment"]
    row = ["Math", "2026-10-01", "1/2", "", "", "", "", "", "", "Graded", "=HYPERLINK(\"x\")"]
    out = _written([header, row])
    assert out[1][2] == "'1/2"
    assert out[1][10] == "'=HYPERLINK(\"x\")"


def test_plus_minus_at_and_plain_numbers_are_escaped():
    header = ["h"] * 11
    row = ["+2 if resubmitted", "2026-10-01", "-5 late", "", "", "", "", "", "", "Graded", "@mention"]
    out = _written([header, row, ["2024", "2026-10-01", "3.5", "", "", "", "", "", "", "", "3-4"]])
    assert [out[1][0], out[1][2], out[1][10]] == ["'+2 if resubmitted", "'-5 late", "'@mention"]
    assert [out[2][0], out[2][2], out[2][10]] == ["'2024", "'3.5", "'3-4"]


def test_ordinary_text_dates_numbers_and_header_are_untouched():
    header = ["Class", "Due Date", "Assignment", "Score (raw)", "Earned", "Possible", "Percent", "Missing", "Zero",
              "Status", "Comment"]
    row = ["Math", "2026-10-01", "2.1 Eras Gallery Walk", "3/5(60%)", 3.0, 5.0, 0.6, "Y", "", "Graded", "Nice work"]
    out = _written([header, row])
    assert out[0] == header
    assert out[1] == row
