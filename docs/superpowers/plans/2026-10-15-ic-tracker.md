# ic-tracker Implementation Plan

> **AMENDMENT NOTE:** This is the original implementation plan. Later changes (grades column, teacher comments and upcoming items, TRACKER_STUDENTS, weekday schedule, dry-run reading History) are recorded as amendments in the spec (`docs/superpowers/specs/2026-10-15-ic-tracker-design.md`), which supersedes any conflicting task here.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A daily job that fetches Alex's current-term Infinite Campus assignments, writes a dated tab plus a History row set to a Google Sheet, and emails a trend report.

**Architecture:** New package `src/ic_tracker` next to the unchanged-API `ic_parent_api` library. Pure modules (`model`, `analysis`, `report/*`, `config`, `backfill`) hold all logic; Google and Infinite Campus access sit behind thin gateway classes that take an injected API service object, so everything is testable with fakes. `runner.run_report` orchestrates the fixed order: write tab, upsert History, read History, render, send.

**Tech Stack:** Python 3.13 (library floor 3.9, so tracker modules use `from __future__ import annotations`), pytest, Playwright, `google-api-python-client`, `google-auth-oauthlib`, python-dotenv, launchd.

**Spec:** `docs/superpowers/specs/2026-10-15-ic-tracker-design.md`

## Global Constraints
- Run time: daily **07:00 America/Denver**; timezone setting `TRACKER_TIMEZONE`, default `America/Denver`.
- Google scopes: `https://www.googleapis.com/auth/drive`, `https://www.googleapis.com/auth/spreadsheets`, `https://www.googleapis.com/auth/gmail.send`.
- Cache files live in `~/.cache/ic-tracker/` with mode 600: `google_client.json`, `google_token.json` (contains `issued_at`).
- Refresh-token lifetime in Testing status: `TRACKER_TOKEN_TTL_DAYS`, default 7; the value `none` disables the reminder.
- Problem assignment = flagged missing, or graded with score 0 and not missing. Excused (`e`) and absent (`Ab`) are never problems. Needs attention = missing + zeros, no double counting.
- Excluded courses: prefix match, case-insensitive, `TRACKER_EXCLUDE_COURSES`, default `Seminar`.
- Email subject: `Alex: assignment check-in, Thu Oct 15` (neutral; no counts). No grade percentages in the email. No red in the email grid.
- Trend columns are runs (previous 7 + today), not calendar days.
- Testing phase: `TRACKER_EMAIL_TO=parent1@example.com`, `TRACKER_EMAIL_CC` empty. Live: `TO=student@example.com`, `CC=parent2@example.com,parent1@example.com`.
- The tool never changes Drive permissions.
- Tests never call Google or Infinite Campus and contain no real credentials or student data.
- **Commit steps are gated:** they run only when the user has asked for commits. The overnight build leaves all changes uncommitted.

## Review Focus
- A class that has problems in earlier runs but is absent from today's data: the trend grid shows `0`, not a missing cell or a crash (Task 3).
- Assignment or course names containing `& < > " '`: the email HTML escapes them (Task 6).
- An assignment with no due date: sorting and the tab rows do not crash, due cell is blank (Tasks 3, 5).
- Rerunning on the same date after a problem was fixed: stale red fills and old rows are gone, History has exactly one row set for that date (Task 8).
- Token age of exactly the TTL, past the TTL, and `ttl=None`: footer text is correct ("expires today", "expired", omitted) (Tasks 6, 7).
- First ever run (History has only today): the email renders a one-column grid and omits "Last run"/"One week ago" (Tasks 3, 6).
- Excused (`e`) and absent (`Ab`) scores never count as zeros or missing (Tasks 3, 4).

---

## File Structure
```
pyproject.toml                         modify: tracker extra, console script, pytest config
.gitignore                             modify: stop ignoring tests/, add .env.example exception
.env.example                           create
src/ic_tracker/__init__.py             create
src/ic_tracker/config.py               Settings + load_settings (pure)
src/ic_tracker/model.py                NormalizedAssignment + status constants (pure)
src/ic_tracker/analysis.py             filter/sort/classify/summarize/trend (pure)
src/ic_tracker/ic/__init__.py
src/ic_tracker/ic/sso.py               Playwright SSO login -> cookies
src/ic_tracker/ic/source.py            normalize(), current term, fetch
src/ic_tracker/report/__init__.py
src/ic_tracker/report/sheet.py         TabData builder (pure)
src/ic_tracker/report/email.py         EmailContent renderer (pure)
src/ic_tracker/google/__init__.py
src/ic_tracker/google/auth.py          OAuth, token cache, credentials, services
src/ic_tracker/google/sheets.py        SheetsGateway
src/ic_tracker/google/drive.py         DriveGateway
src/ic_tracker/google/gmail.py         GmailGateway + MIME builder
src/ic_tracker/alert.py                macOS notification + best-effort failure email
src/ic_tracker/backfill.py             History backfill + migrate()
src/ic_tracker/runner.py               prepare/run_report/write_dry_run
src/ic_tracker/cli.py                  argparse commands and exit codes
deploy/com.mindenhall.ic-tracker.plist.template
deploy/install_launchd.sh
tests/__init__.py, tests/ic_tracker/__init__.py, tests/ic_tracker/builders.py
tests/ic_tracker/test_*.py             one per module
example.py                             modify: use ic_tracker modules
sso_login.py normalized.py summary.py current_assignments.py   delete (moved)
README.md                              modify: tracker section
```

---

### Task 1: Packaging and test infrastructure

**Files:**
- Modify: `pyproject.toml`, `.gitignore`
- Create: `src/ic_tracker/__init__.py`, `tests/__init__.py`, `tests/ic_tracker/__init__.py`, `tests/ic_tracker/builders.py`, `tests/ic_tracker/test_package.py`

**Interfaces:**
- Produces: importable `ic_tracker`; `tests.ic_tracker.builders.make_assignment(**overrides) -> NormalizedAssignment` plus `make_missing`, `make_zero`, `make_excused`, `make_ungraded` (defined in Task 3 once the model exists; this task only creates the empty package).

- [ ] **Step 1: Write the failing test**

`tests/ic_tracker/test_package.py`:
```python
import ic_tracker


def test_package_has_version():
    assert ic_tracker.__version__ == "0.1.0"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/ic_tracker/test_package.py -q`
Expected: error (`pytest` not installed, or `ModuleNotFoundError: ic_tracker`).

- [ ] **Step 3: Implement**

`pyproject.toml`: append after `dependencies = [...]`:
```toml
[project.optional-dependencies]
tracker = [
    "playwright>=1.40",
    "python-dotenv>=1.0",
    "google-api-python-client>=2.100",
    "google-auth-oauthlib>=1.2",
    "pytest>=7.1",
]

[project.scripts]
ic-tracker = "ic_tracker.cli:main"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src", "."]
```
`.gitignore`: delete the line `tests/`.
`src/ic_tracker/__init__.py`:
```python
"""ic-tracker: daily Infinite Campus assignment report for a parent."""
__version__ = "0.1.0"
```
Create empty `tests/__init__.py` and `tests/ic_tracker/__init__.py`.
Run: `.venv/bin/pip install -q -e ".[tracker]"`

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/ic_tracker/test_package.py -q`
Expected: `1 passed`

- [ ] **Step 5: Commit** [commit-gated] `git add pyproject.toml .gitignore src/ic_tracker tests && git commit -m "ic-tracker: package skeleton and test config"`

---

### Task 2: Configuration

**Files:**
- Create: `src/ic_tracker/config.py`, `tests/ic_tracker/test_config.py`, `.env.example`

**Interfaces:**
- Produces:
  - `class ConfigError(Exception)`
  - `@dataclass(frozen=True) class Settings` with fields `ic_base_url: str, ic_username: str, ic_password: str, ic_district: str, email_to: tuple[str, ...], email_cc: tuple[str, ...] = (), alert_to: tuple[str, ...] = (), student: str = "alex", timezone: str = "America/Denver", exclude_courses: tuple[str, ...] = ("Seminar",), token_ttl_days: int | None = 7, sheet_name: str = "Assignments Tracker", drive_folder: str = "Kids/Alex", cache_dir: Path = ~/.cache/ic-tracker, op_client_id_ref: str, op_client_secret_ref: str`
  - `load_settings(env: Mapping[str, str]) -> Settings`

- [ ] **Step 1: Write the failing tests**

`tests/ic_tracker/test_config.py`:
```python
from pathlib import Path

import pytest

from ic_tracker.config import ConfigError, load_settings

BASE = {
    "IC_BASE_URL": "https://x.infinitecampus.org",
    "IC_USERNAME": "u",
    "IC_PASSWORD": "p",
    "IC_DISTRICT": "d",
    "TRACKER_EMAIL_TO": "a@example.com",
}


def test_defaults():
    s = load_settings(BASE)
    assert s.email_to == ("a@example.com",)
    assert s.email_cc == () and s.alert_to == ()
    assert s.student == "alex"
    assert s.timezone == "America/Denver"
    assert s.exclude_courses == ("Seminar",)
    assert s.token_ttl_days == 7
    assert s.sheet_name == "Assignments Tracker"
    assert s.drive_folder == "Kids/Alex"
    assert s.cache_dir == Path.home() / ".cache" / "ic-tracker"


def test_lists_are_split_and_trimmed():
    env = {**BASE, "TRACKER_EMAIL_TO": " a@x.com , b@x.com ", "TRACKER_EMAIL_CC": "c@x.com,,",
           "TRACKER_EXCLUDE_COURSES": "Seminar, Advisement"}
    s = load_settings(env)
    assert s.email_to == ("a@x.com", "b@x.com")
    assert s.email_cc == ("c@x.com",)
    assert s.exclude_courses == ("Seminar", "Advisement")


@pytest.mark.parametrize("raw,expected", [("none", None), ("None", None), ("", None), ("5", 5)])
def test_token_ttl(raw, expected):
    assert load_settings({**BASE, "TRACKER_TOKEN_TTL_DAYS": raw}).token_ttl_days == expected


def test_missing_required_lists_every_missing_name():
    with pytest.raises(ConfigError) as err:
        load_settings({"IC_BASE_URL": "x"})
    for name in ("IC_USERNAME", "IC_PASSWORD", "IC_DISTRICT", "TRACKER_EMAIL_TO"):
        assert name in str(err.value)


def test_bad_ttl_is_a_config_error():
    with pytest.raises(ConfigError):
        load_settings({**BASE, "TRACKER_TOKEN_TTL_DAYS": "soon"})
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/ic_tracker/test_config.py -q`
Expected: `ModuleNotFoundError: ic_tracker.config`

- [ ] **Step 3: Implement**

`src/ic_tracker/config.py`:
```python
"""Settings loaded from environment variables (usually a .env file)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

_REQUIRED = ("IC_BASE_URL", "IC_USERNAME", "IC_PASSWORD", "IC_DISTRICT", "TRACKER_EMAIL_TO")
_OP_ITEM = "op://Private/Google Personal Automation Hub OAuth"


class ConfigError(Exception):
    """Settings are missing or invalid."""


def _split(raw: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _ttl(raw: str) -> Optional[int]:
    value = raw.strip().lower()
    if value in ("", "none"):
        return None
    try:
        return int(value)
    except ValueError as error:
        raise ConfigError(f"TRACKER_TOKEN_TTL_DAYS must be a whole number or 'none', got {raw!r}") from error


@dataclass(frozen=True)
class Settings:
    ic_base_url: str
    ic_username: str
    ic_password: str
    ic_district: str
    email_to: tuple[str, ...]
    email_cc: tuple[str, ...] = ()
    alert_to: tuple[str, ...] = ()
    student: str = "alex"
    timezone: str = "America/Denver"
    exclude_courses: tuple[str, ...] = ("Seminar",)
    token_ttl_days: Optional[int] = 7
    sheet_name: str = "Assignments Tracker"
    drive_folder: str = "Kids/Alex"
    cache_dir: Path = Path.home() / ".cache" / "ic-tracker"
    op_client_id_ref: str = f"{_OP_ITEM}/client_id"
    op_client_secret_ref: str = f"{_OP_ITEM}/client_secret"


def load_settings(env: Mapping[str, str]) -> Settings:
    missing = [name for name in _REQUIRED if not env.get(name)]
    if missing:
        raise ConfigError("Missing required settings: " + ", ".join(missing))
    defaults = Settings("", "", "", "", ())
    return Settings(
        ic_base_url=env["IC_BASE_URL"],
        ic_username=env["IC_USERNAME"],
        ic_password=env["IC_PASSWORD"],
        ic_district=env["IC_DISTRICT"],
        email_to=_split(env["TRACKER_EMAIL_TO"]),
        email_cc=_split(env.get("TRACKER_EMAIL_CC", "")),
        alert_to=_split(env.get("TRACKER_ALERT_TO", "")),
        student=env.get("TRACKER_STUDENT", defaults.student),
        timezone=env.get("TRACKER_TIMEZONE", defaults.timezone),
        exclude_courses=_split(env["TRACKER_EXCLUDE_COURSES"]) if "TRACKER_EXCLUDE_COURSES" in env
        else defaults.exclude_courses,
        token_ttl_days=_ttl(env["TRACKER_TOKEN_TTL_DAYS"]) if "TRACKER_TOKEN_TTL_DAYS" in env
        else defaults.token_ttl_days,
        sheet_name=env.get("TRACKER_SHEET_NAME", defaults.sheet_name),
        drive_folder=env.get("TRACKER_DRIVE_FOLDER", defaults.drive_folder),
        cache_dir=Path(env["TRACKER_CACHE_DIR"]).expanduser() if "TRACKER_CACHE_DIR" in env
        else defaults.cache_dir,
        op_client_id_ref=env.get("TRACKER_OP_CLIENT_ID_REF", defaults.op_client_id_ref),
        op_client_secret_ref=env.get("TRACKER_OP_CLIENT_SECRET_REF", defaults.op_client_secret_ref),
    )
```
`.env.example`:
```
# Infinite Campus (Jeffco SSO login)
IC_BASE_URL=https://jeffco.infinitecampus.org
IC_USERNAME=
IC_PASSWORD=
IC_DISTRICT=Jeffco_IC

# Email (testing: to yourself only; live: TO=kid, CC=both parents)
TRACKER_EMAIL_TO=parent1@example.com
TRACKER_EMAIL_CC=
TRACKER_ALERT_TO=

# Optional overrides (defaults shown)
# TRACKER_STUDENT=alex
# TRACKER_TIMEZONE=America/Denver
# TRACKER_EXCLUDE_COURSES=Seminar
# TRACKER_TOKEN_TTL_DAYS=7        # 'none' once the Google app is in Production
# TRACKER_SHEET_NAME=Assignments Tracker
# TRACKER_DRIVE_FOLDER=Kids/Alex
```

- [ ] **Step 4: Run to verify pass** — `.venv/bin/python -m pytest tests/ic_tracker/test_config.py -q` → all pass.
- [ ] **Step 5: Commit** [commit-gated]

---

### Task 3: Model and analysis (pure logic)

**Files:**
- Create: `src/ic_tracker/model.py`, `src/ic_tracker/analysis.py`, `tests/ic_tracker/builders.py` (contents below), `tests/ic_tracker/test_analysis.py`

**Interfaces:**
- Produces (`model.py`): constants `STATUS_MISSING="Missing"`, `STATUS_EXCUSED="Excused"`, `STATUS_ABSENT="Absent"`, `STATUS_GRADED="Graded"`, `STATUS_NOT_GRADED="Not graded"`; `@dataclass(frozen=True) NormalizedAssignment(id:int, course:str, name:str, due:datetime|None, assigned:datetime|None, graded_at:datetime|None, term_ids:tuple[int,...], score:float|None, total:float|None, percent:float|None, score_raw:str|None, status:str, is_graded:bool, is_rubric:bool, missing:bool, late:bool, incomplete:bool, turned_in:bool, comments:str|None, feedback:str|None)` with property `score_display -> str`.
- Produces (`analysis.py`): `KIND_MISSING`, `KIND_ZERO`; `problem_kind(a)->str|None`; `exclude_courses(assignments, prefixes)->list`; `sort_assignments(assignments)->list`; `ClassCounts(course, assignments, missing, zeros)` with `needs_attention`; `summarize_by_class(assignments)->list[ClassCounts]`; `total_of(counts)->ClassCounts`; `HistoryRow(run_date, course, assignments, missing, zeros)` with `needs_attention` and `from_counts(run_date, counts)`; `Trend(dates, courses, totals_by_date, _cells)` with `count(course, d)`, `total(d)`, `run_date`, `previous_total`, `week_ago_total`; `build_trend(rows, run_date, previous_runs=7)->Trend`.

- [ ] **Step 1: Write builders and failing tests**

`tests/ic_tracker/builders.py`:
```python
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
```

`tests/ic_tracker/test_analysis.py`:
```python
from datetime import date, datetime, timezone

from ic_tracker.analysis import (ClassCounts, HistoryRow, KIND_MISSING, KIND_ZERO, build_trend,
                                 exclude_courses, problem_kind, sort_assignments, summarize_by_class,
                                 total_of)
from tests.ic_tracker.builders import (make_absent, make_assignment, make_excused, make_missing,
                                       make_ungraded, make_zero)


def test_problem_kind():
    assert problem_kind(make_missing()) == KIND_MISSING
    assert problem_kind(make_zero()) == KIND_ZERO
    assert problem_kind(make_assignment()) is None
    assert problem_kind(make_ungraded()) is None


def test_excused_and_absent_are_never_problems():
    assert problem_kind(make_excused()) is None
    assert problem_kind(make_absent()) is None


def test_missing_wins_over_zero_so_nothing_is_double_counted():
    counts = summarize_by_class([make_missing(), make_zero()])
    assert (counts[0].missing, counts[0].zeros, counts[0].needs_attention) == (1, 1, 2)
    assert summarize_by_class([make_missing()])[0].zeros == 0


def test_exclude_courses_prefix_case_insensitive():
    items = [make_assignment(course="Seminar 12"), make_assignment(course="seminar"), make_assignment(course="Math")]
    assert [a.course for a in exclude_courses(items, ("Seminar",))] == ["Math"]
    assert len(exclude_courses(items, ())) == 3


def test_sort_by_course_then_due_and_none_due_last():
    early = datetime(2026, 9, 1, tzinfo=timezone.utc)
    late = datetime(2026, 9, 9, tzinfo=timezone.utc)
    items = [make_assignment(course="B", due=early), make_assignment(course="A", due=late, name="z"),
             make_assignment(course="A", due=None, name="none"), make_assignment(course="A", due=early, name="e")]
    ordered = [(a.course, a.name) for a in sort_assignments(items)]
    assert ordered == [("A", "e"), ("A", "z"), ("A", "none"), ("B", "Homework")]


def test_summarize_by_class_and_total():
    counts = summarize_by_class([make_assignment(course="B"), make_missing(course="A"), make_zero(course="A"),
                                 make_assignment(course="A")])
    assert [c.course for c in counts] == ["A", "B"]
    assert counts[0] == ClassCounts("A", 3, 1, 1)
    total = total_of(counts)
    assert (total.course, total.assignments, total.needs_attention) == ("Total", 4, 2)


def _rows(d, **by_course):
    return [HistoryRow(d, c, 10, n, 0) for c, n in by_course.items()]


def test_trend_window_is_previous_seven_runs_plus_today():
    rows = []
    for day in range(1, 11):
        rows += _rows(date(2026, 10, day), Math=day)
    trend = build_trend(rows, date(2026, 10, 10))
    assert trend.dates[0] == date(2026, 10, 3) and trend.dates[-1] == date(2026, 10, 10)
    assert len(trend.dates) == 8
    assert trend.total(date(2026, 10, 10)) == 10
    assert trend.previous_total == 9


def test_trend_class_missing_on_some_dates_counts_zero():
    rows = _rows(date(2026, 10, 1), Math=2, Art=1) + _rows(date(2026, 10, 2), Math=1)
    trend = build_trend(rows, date(2026, 10, 2))
    assert trend.courses == ("Art", "Math")
    assert trend.count("Art", date(2026, 10, 2)) == 0
    assert trend.count("Art", date(2026, 10, 1)) == 1


def test_first_run_has_one_column_and_no_comparisons():
    trend = build_trend(_rows(date(2026, 10, 2), Math=3), date(2026, 10, 2))
    assert trend.dates == (date(2026, 10, 2),)
    assert trend.previous_total is None and trend.week_ago_total is None


def test_week_ago_total_uses_latest_run_on_or_before_seven_days_earlier():
    rows = _rows(date(2026, 10, 1), Math=9) + _rows(date(2026, 10, 7), Math=5) + _rows(date(2026, 10, 9), Math=4)
    # Oct 9 minus 7 days = Oct 2; the latest run on or before Oct 2 is Oct 1.
    assert build_trend(rows, date(2026, 10, 9)).week_ago_total == 9
    assert build_trend(rows, date(2026, 10, 7)).week_ago_total is None  # nothing on or before Sep 30


def test_history_row_from_counts():
    row = HistoryRow.from_counts(date(2026, 10, 2), ClassCounts("Math", 5, 2, 1))
    assert (row.run_date, row.course, row.assignments, row.needs_attention) == (date(2026, 10, 2), "Math", 5, 3)
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/python -m pytest tests/ic_tracker/test_analysis.py -q` → `ModuleNotFoundError: ic_tracker.model`.

- [ ] **Step 3: Implement**

`src/ic_tracker/model.py`:
```python
"""Normalized assignment: parsed types, explicit grading state."""
from __future__ import annotations

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
```
`src/ic_tracker/analysis.py`:
```python
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
```

- [ ] **Step 4: Run to verify pass** — `.venv/bin/python -m pytest tests/ic_tracker/test_analysis.py -q` → all pass.
- [ ] **Step 5: Commit** [commit-gated]

---

### Task 4: Infinite Campus source (normalize, current term, fetch, SSO)

**Files:**
- Create: `src/ic_tracker/ic/__init__.py`, `src/ic_tracker/ic/sso.py` (moved from `sso_login.py`), `src/ic_tracker/ic/source.py`, `tests/ic_tracker/test_source.py`

**Interfaces:**
- Consumes: `Settings` (Task 2), `NormalizedAssignment`/status constants (Task 3), library `InfiniteCampus(..., cookies=)`.
- Produces: `StudentNotFoundError`; `normalize(a) -> NormalizedAssignment` (takes the library `Assignment`); `find_student(students, first_name)`; `async current_term(client, assignments, today) -> Term | None`; `@dataclass(frozen=True) FetchResult(student_first_name:str, term_name:str|None, term_start:str|None, term_end:str|None, assignments:list[NormalizedAssignment])`; `async fetch_student_data(client, first_name, today) -> FetchResult`; `async fetch(settings, today) -> FetchResult`; `async sso_login(base_url, username, password, headless=True, timeout=30000) -> dict`.

- [ ] **Step 1: Write failing tests**

`tests/ic_tracker/test_source.py`:
```python
import asyncio
from datetime import date
from types import SimpleNamespace as NS

import pytest

from ic_tracker.ic.source import StudentNotFoundError, fetch_student_data, find_student, normalize
from ic_tracker.model import STATUS_ABSENT, STATUS_EXCUSED, STATUS_GRADED, STATUS_MISSING, STATUS_NOT_GRADED


def raw(**kw):
    base = dict(objectsectionid=1, coursename="Math", assignmentname="HW", duedate="2026-09-07T05:59:00.000Z",
                assigneddate="2026-09-06T06:00:00.000Z", scoremodifieddate="2026-10-13T14:34:00.000Z",
                termids=[10], comments=None, feedback=None, missing=False, late=False, incomplete=False,
                turnedin=True, score=None, scorepoints=None, scorepercentage=None, totalpoints=None,
                active=True, structureid=100)
    base.update(kw)
    return NS(**base)


def test_point_score_is_parsed():
    n = normalize(raw(score="2", scorepoints="2.0", scorepercentage="40.0", totalpoints=5))
    assert (n.score, n.total, n.percent, n.status, n.is_graded, n.is_rubric) == (2.0, 5.0, 40.0, STATUS_GRADED, True, False)
    assert n.due.isoformat() == "2026-09-07T05:59:00+00:00"
    assert n.term_ids == (10,)


def test_rubric_score_has_no_total_or_percent():
    n = normalize(raw(score="3", scorepoints="3.0"))
    assert (n.percent, n.is_rubric, n.status) == (None, True, STATUS_GRADED)


def test_missing_item_has_null_score_but_zero_points():
    n = normalize(raw(score=None, scorepoints="0.0", totalpoints=25, missing=True))
    assert (n.status, n.score, n.is_graded, n.missing) == (STATUS_MISSING, 0.0, True, True)


def test_excused_and_absent_are_not_graded():
    e = normalize(raw(score="e", totalpoints=25))
    a = normalize(raw(score="Ab", totalpoints=5))
    assert (e.status, e.is_graded, e.score) == (STATUS_EXCUSED, False, None)
    assert (a.status, a.is_graded, a.score) == (STATUS_ABSENT, False, None)


def test_ungraded_and_null_flags():
    n = normalize(raw(missing=None, late=None, incomplete=None, turnedin=None))
    assert (n.status, n.is_graded, n.missing, n.late, n.turned_in) == (STATUS_NOT_GRADED, False, False, False, False)


def test_missing_due_date_is_none():
    assert normalize(raw(duedate=None)).due is None


class FakeClient:
    def __init__(self, students, assignments, terms):
        self._s, self._a, self._t = students, assignments, terms

    async def students(self):
        return self._s

    async def assignments(self, person_id):
        return self._a[person_id]

    async def terms(self, structure_id):
        return self._t[structure_id]


def student(first, pid):
    return NS(firstname=first, lastname="M", alias=None, personid=pid)


def term(tid, name, start, end):
    return NS(termid=tid, termname=name, startdate=start, enddate=end)


def test_find_student_is_case_insensitive_and_lists_names_on_miss():
    students = [student("Alex", 1), student("Sam", 2)]
    assert find_student(students, "ALEX").personid == 1
    with pytest.raises(StudentNotFoundError) as err:
        find_student(students, "bob")
    assert "Alex" in str(err.value) and "Sam" in str(err.value)


def test_fetch_picks_current_term_and_filters_inactive():
    client = FakeClient(
        [student("Alex", 1)],
        {1: [raw(objectsectionid=1, termids=[20]), raw(objectsectionid=2, termids=[10]),
             raw(objectsectionid=3, termids=[20], active=False)]},
        {100: [term(10, "S1", "2026-08-19", "2026-12-18"), term(20, "S2", "2027-01-06", "2027-05-27")]})
    result = asyncio.run(fetch_student_data(client, "alex", date(2026, 10, 14)))
    assert result.term_name == "S1"
    assert [a.id for a in result.assignments] == [2]
    assert result.student_first_name == "Alex"


def test_fetch_with_no_started_term_returns_no_term():
    client = FakeClient([student("Alex", 1)], {1: [raw()]}, {100: [term(10, "S1", "2026-08-19", "2026-12-18")]})
    result = asyncio.run(fetch_student_data(client, "alex", date(2026, 1, 1)))
    assert result.term_name is None and result.assignments == []
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/python -m pytest tests/ic_tracker/test_source.py -q` → `ModuleNotFoundError: ic_tracker.ic`.

- [ ] **Step 3: Implement**

Move `sso_login.py` → `src/ic_tracker/ic/sso.py` (add `from __future__ import annotations`; function unchanged). Create empty `src/ic_tracker/ic/__init__.py`.

`src/ic_tracker/ic/source.py`:
```python
"""Fetch a student's current-term assignments and normalize them."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from ic_parent_api import InfiniteCampus

from ic_tracker.config import Settings
from ic_tracker.ic.sso import sso_login
from ic_tracker.model import (NormalizedAssignment, STATUS_ABSENT, STATUS_EXCUSED, STATUS_GRADED,
                              STATUS_MISSING, STATUS_NOT_GRADED)


class StudentNotFoundError(Exception):
    """No student matches the requested first name."""


def _float(value) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dt(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def _status(missing: bool, score_raw: Optional[str], graded: bool) -> str:
    if missing:
        return STATUS_MISSING
    raw = (score_raw or "").strip().lower()
    if raw == "e":
        return STATUS_EXCUSED
    if raw == "ab":
        return STATUS_ABSENT
    return STATUS_GRADED if graded else STATUS_NOT_GRADED


def normalize(a) -> NormalizedAssignment:
    score = _float(a.scorepoints if a.scorepoints is not None else a.score)
    total = _float(a.totalpoints) or None
    percent = _float(a.scorepercentage)
    if percent is None and score is not None and total:
        percent = score / total * 100
    graded = score is not None
    missing = bool(a.missing)
    return NormalizedAssignment(
        id=a.objectsectionid, course=a.coursename, name=a.assignmentname,
        due=_dt(a.duedate), assigned=_dt(a.assigneddate), graded_at=_dt(a.scoremodifieddate),
        term_ids=tuple(a.termids), score=score, total=total, percent=percent, score_raw=a.score,
        status=_status(missing, a.score, graded), is_graded=graded, is_rubric=graded and total is None,
        missing=missing, late=bool(a.late), incomplete=bool(a.incomplete), turned_in=bool(a.turnedin),
        comments=a.comments, feedback=a.feedback)


def find_student(students, first_name: str):
    wanted = first_name.strip().lower()
    matches = [s for s in students if wanted in (s.firstname.lower(), (s.alias or "").lower())]
    if not matches:
        names = ", ".join(s.firstname for s in students)
        raise StudentNotFoundError(f"No student named '{first_name}'. Available: {names}")
    return matches[0]


async def current_term(client, assignments, today: date):
    """The term that started most recently on or before today, across the student's schedule structures."""
    today_iso = today.isoformat()
    terms = []
    for structure_id in sorted({a.structureid for a in assignments}):
        terms.extend(await client.terms(structure_id))
    started = [t for t in terms if t.startdate <= today_iso]
    return max(started, key=lambda t: t.startdate, default=None)


@dataclass(frozen=True)
class FetchResult:
    student_first_name: str
    term_name: Optional[str]
    term_start: Optional[str]
    term_end: Optional[str]
    assignments: list


async def fetch_student_data(client, first_name: str, today: date) -> FetchResult:
    student = find_student(await client.students(), first_name)
    raw_assignments = await client.assignments(student.personid)
    term = await current_term(client, raw_assignments, today)
    if term is None:
        return FetchResult(student.firstname, None, None, None, [])
    in_term = [a for a in raw_assignments if term.termid in a.termids and a.active is not False]
    return FetchResult(student.firstname, term.termname, term.startdate, term.enddate,
                       [normalize(a) for a in in_term])


async def fetch(settings: Settings, today: date) -> FetchResult:
    cookies = await sso_login(settings.ic_base_url, settings.ic_username, settings.ic_password)
    client = InfiniteCampus(settings.ic_base_url, settings.ic_username, settings.ic_password,
                            settings.ic_district, cookies=cookies)
    return await fetch_student_data(client, settings.student, today)
```

- [ ] **Step 4: Run to verify pass** — `.venv/bin/python -m pytest tests/ic_tracker/test_source.py -q` → all pass.
- [ ] **Step 5: Commit** [commit-gated]

---

### Task 5: Sheet tab builder

**Files:**
- Create: `src/ic_tracker/report/__init__.py`, `src/ic_tracker/report/sheet.py`, `tests/ic_tracker/test_report_sheet.py`

**Interfaces:**
- Consumes: `NormalizedAssignment`, `ClassCounts`, `total_of`, `problem_kind`.
- Produces: `TAB_HEADER`, `STATS_HEADER`; `@dataclass(frozen=True) TabData(values: list[list], highlight_rows: tuple[int, ...], data_cols: int, total_cols: int)`; `build_tab(assignments, counts, tz: tzinfo) -> TabData`. `values[0]` is the header row; `highlight_rows` are indexes into `values`.

- [ ] **Step 1: Write failing tests**

`tests/ic_tracker/test_report_sheet.py`:
```python
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from ic_tracker.analysis import summarize_by_class
from ic_tracker.report.sheet import STATS_HEADER, TAB_HEADER, build_tab
from tests.ic_tracker.builders import (make_absent, make_assignment, make_excused, make_missing, make_ungraded,
                                       make_zero)

DENVER = ZoneInfo("America/Denver")


def build(items):
    return build_tab(items, summarize_by_class(items), DENVER)


def test_header_row_has_tab_columns_then_stats_block_after_a_gap():
    tab = build([make_assignment()])
    assert tab.values[0] == TAB_HEADER + [""] + STATS_HEADER
    assert (tab.data_cols, tab.total_cols) == (11, 17)


def test_graded_row_values_and_local_due_date():
    # 05:59Z is 23:59 the previous day in Denver
    a = make_assignment(course="Math", name="HW", due=datetime(2026, 9, 8, 5, 59, tzinfo=timezone.utc),
                        score=18.0, total=20.0, percent=90.0, score_raw="18")
    row = build([a]).values[1]
    assert row[:11] == ["Math", "2026-09-07", "HW", "18/20(90%)", 18.0, 20.0, 0.9, "", "", "Graded", ""]


def test_missing_row_is_flagged_and_highlighted():
    tab = build([make_assignment(name="ok"), make_missing(name="gone", total=25.0)])
    row = tab.values[2]
    assert row[7] == "Y" and row[8] == "Y" and row[9] == "Missing"
    assert tab.highlight_rows == (2,)


def test_zero_row_is_highlighted_and_excused_absent_ungraded_are_not():
    items = [make_zero(name="z"), make_excused(name="e"), make_absent(name="a"), make_ungraded(name="u")]
    tab = build(items)
    assert tab.highlight_rows == (1,)
    by_name = {r[2]: r for r in tab.values[1:]}
    assert by_name["e"][3] == "e" and by_name["e"][9] == "Excused"
    assert by_name["a"][3] == "Ab" and by_name["a"][9] == "Absent"
    assert by_name["u"][3] == "" and by_name["u"][9] == "Not graded"
    assert by_name["z"][8] == "Y" and by_name["z"][7] == ""


def test_rubric_row_shows_level_only():
    row = build([make_assignment(score=3.0, total=None, percent=None, is_rubric=True, score_raw="3")]).values[1]
    assert row[3] == "3" and row[4] == 3.0 and row[5] == "" and row[6] == ""


def test_no_due_date_gives_blank_cell():
    assert build([make_assignment(due=None)]).values[1][1] == ""


def test_comment_prefers_comments_then_feedback():
    assert build([make_assignment(comments="c", feedback="f")]).values[1][10] == "c"
    assert build([make_assignment(feedback="f")]).values[1][10] == "f"


def test_stats_block_lists_classes_and_total_beside_data_rows():
    items = [make_missing(course="A"), make_assignment(course="A"), make_zero(course="B")]
    values = build(items).values
    assert values[1][12:17] == ["A", 2, 1, 0, 1]
    assert values[2][12:17] == ["B", 1, 0, 1, 1]
    assert values[3][12:17] == ["Total", 3, 1, 1, 2]


def test_stats_block_longer_than_data_still_written():
    items = [make_assignment(course=c) for c in ("A", "B")]  # 2 rows, 3 stats rows (A, B, Total)
    assert len(build(items).values) == 4
    assert build(items).values[3][:11] == [""] * 11
    assert build(items).values[3][12] == "Total"
```

- [ ] **Step 2: Run to verify failure** — expect `ModuleNotFoundError: ic_tracker.report`.

- [ ] **Step 3: Implement**

`src/ic_tracker/report/sheet.py`:
```python
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
```

- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** [commit-gated]

---

### Task 6: Email renderer

**Files:**
- Create: `src/ic_tracker/report/email.py`, `tests/ic_tracker/test_report_email.py`

**Interfaces:**
- Consumes: `Trend`, `NormalizedAssignment`, `problem_kind`, `KIND_*`.
- Produces: `@dataclass(frozen=True) EmailContext(student_name:str, run_date:date, trend:Trend, problems:list[NormalizedAssignment], tab_url:str, tab_title:str, token_days_remaining:int|None, tz:tzinfo)`; `@dataclass(frozen=True) EmailContent(subject:str, html:str, text:str)`; `render_email(ctx) -> EmailContent`; `token_footer(days: int|None) -> tuple[str, bool]` returning (text, emphasized).

- [ ] **Step 1: Write failing tests**

`tests/ic_tracker/test_report_email.py`:
```python
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from ic_tracker.analysis import HistoryRow, build_trend
from ic_tracker.report.email import EmailContext, render_email, token_footer
from tests.ic_tracker.builders import make_missing, make_zero

TZ = ZoneInfo("America/Denver")
D = date(2026, 10, 15)


def ctx(rows=None, problems=None, days=7, **kw):
    rows = rows if rows is not None else [HistoryRow(D, "Math", 10, 2, 1)]
    problems = problems if problems is not None else [make_missing(course="Math", name="Worksheet"),
                                                      make_zero(course="Math", name="Quiz")]
    base = dict(student_name="Alex", run_date=D, trend=build_trend(rows, D), problems=problems,
                tab_url="https://docs.google.com/spreadsheets/d/S/edit#gid=5", tab_title="2026-10-15",
                token_days_remaining=days, tz=TZ)
    base.update(kw)
    return EmailContext(**base)


def test_subject_is_neutral():
    assert render_email(ctx()).subject == "Alex: assignment check-in, Thu Oct 15"


def test_summary_line_and_comparisons():
    rows = [HistoryRow(date(2026, 10, 7), "Math", 10, 9, 0), HistoryRow(date(2026, 10, 14), "Math", 10, 5, 0),
            HistoryRow(D, "Math", 10, 2, 1)]
    text = render_email(ctx(rows=rows)).text
    assert "Needs attention today: 3 (1 missing, 1 zero)." in text
    assert "Last run: 5." in text and "One week ago: 9." in text


def test_first_run_omits_comparisons_and_renders_one_column():
    content = render_email(ctx())
    assert "Last run" not in content.text and "One week ago" not in content.text
    assert content.html.count("<th") == 2  # class header + one date column


def test_nothing_to_report_day():
    content = render_email(ctx(rows=[HistoryRow(D, "Math", 10, 0, 0)], problems=[]))
    assert "Nothing needs attention today." in content.text
    assert "Today's items" not in content.text


def test_items_grouped_by_class_with_local_due_date_and_kind():
    p = [make_missing(course="Math", name="Worksheet", due=datetime(2026, 10, 2, 5, 59, tzinfo=timezone.utc))]
    text = render_email(ctx(problems=p)).text
    assert "Math" in text and "Worksheet" in text and "Oct 1" in text and "Missing" in text


def test_link_to_tab_is_present_in_both_parts():
    c = render_email(ctx())
    assert 'href="https://docs.google.com/spreadsheets/d/S/edit#gid=5"' in c.html
    assert "https://docs.google.com/spreadsheets/d/S/edit#gid=5" in c.text
    assert "2026-10-15" in c.html


def test_html_escapes_names():
    p = [make_missing(course="A & B <i>", name='Quiz "1" <script>alert(1)</script>')]
    html = render_email(ctx(problems=p, rows=[HistoryRow(D, "A & B <i>", 3, 1, 0)])).html
    assert "<script>" not in html and "&lt;script&gt;" in html and "A &amp; B &lt;i&gt;" in html


def test_trend_grid_shows_zero_for_class_absent_today():
    rows = [HistoryRow(date(2026, 10, 14), "Art", 4, 3, 0), HistoryRow(D, "Math", 10, 1, 0)]
    text = render_email(ctx(rows=rows)).text
    art_line = next(line for line in text.splitlines() if line.startswith("Art"))
    assert art_line.split()[-2:] == ["3", "0"]


def test_no_percentages_or_red_in_email():
    html = render_email(ctx()).html.lower()
    assert "%" not in html.replace("100%", "").replace("width:100%", "")
    for red in ("#ff0000", "red", "#f4cccc"):
        assert red not in html


def test_token_footer_variants():
    assert token_footer(None) == ("", False)
    assert token_footer(5) == ("Google sign-in expires in 5 days. Renew with: ic-tracker auth", False)
    assert token_footer(1) == ("Google sign-in expires in 1 day. Renew with: ic-tracker auth", True)
    assert token_footer(2)[1] is True and token_footer(3)[1] is False
    assert token_footer(0) == ("Google sign-in expires today. Renew with: ic-tracker auth", True)
    assert token_footer(-2) == ("Google sign-in has expired. Renew with: ic-tracker auth", True)


def test_footer_in_email_only_when_ttl_set():
    assert "ic-tracker auth" in render_email(ctx(days=3)).text
    assert "ic-tracker auth" not in render_email(ctx(days=None)).text
    assert "font-weight:700" in render_email(ctx(days=1)).html
```

- [ ] **Step 2: Run to verify failure** — `ModuleNotFoundError: ic_tracker.report.email`.

- [ ] **Step 3: Implement**

`src/ic_tracker/report/email.py`:
```python
"""Render the daily email (pure; no network)."""
from __future__ import annotations

import html as _html
from dataclasses import dataclass
from datetime import date, tzinfo
from typing import Optional

from ic_tracker.analysis import KIND_MISSING, KIND_ZERO, Trend, problem_kind
from ic_tracker.model import NormalizedAssignment

_ACCENT = "70,110,180"
_TODAY_BORDER = "border-left:2px solid #466eb4;border-right:2px solid #466eb4;"


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


@dataclass(frozen=True)
class EmailContent:
    subject: str
    html: str
    text: str


def _fmt(d: date) -> str:
    return f"{d:%b} {d.day}"


def _zeros(n: int) -> str:
    return f"{n} zero" if n == 1 else f"{n} zeros"


def token_footer(days: Optional[int]) -> tuple:
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


def _grid_html(trend: Trend) -> str:
    biggest = max([trend.count(c, d) for c in trend.courses for d in trend.dates] + [0])
    cell = "padding:4px 10px;text-align:center;"
    head = "".join(
        f'<th style="{cell}font-weight:600;white-space:nowrap;{_TODAY_BORDER if d == trend.run_date else ""}">'
        f"{_html.escape(_fmt(d))}</th>" for d in trend.dates)
    rows = []
    for course in trend.courses:
        cells = "".join(
            f'<td style="{cell}background:{_shade(trend.count(course, d), biggest)};'
            f'{_TODAY_BORDER + "font-weight:600;" if d == trend.run_date else ""}">{trend.count(course, d)}</td>'
            for d in trend.dates)
        rows.append(f'<tr><td style="padding:4px 10px;">{_html.escape(course)}</td>{cells}</tr>')
    totals = "".join(
        f'<td style="{cell}font-weight:700;border-top:1px solid #999;'
        f'{_TODAY_BORDER if d == trend.run_date else ""}">{trend.total(d)}</td>' for d in trend.dates)
    rows.append(f'<tr><td style="padding:4px 10px;font-weight:700;border-top:1px solid #999;">Total</td>{totals}</tr>')
    return ('<table role="presentation" style="border-collapse:collapse;font-size:14px;">'
            f'<tr><th style="padding:4px 10px;text-align:left;">Class</th>{head}</tr>{"".join(rows)}</table>')


def _grid_text(trend: Trend) -> str:
    labels = [_fmt(d) for d in trend.dates]
    name_w = max([len(c) for c in trend.courses] + [len("Class"), len("Total")])
    widths = [max(len(label), 3) + 2 for label in labels]
    lines = ["Class".ljust(name_w) + "".join(label.rjust(w) for label, w in zip(labels, widths))]
    for course in trend.courses:
        lines.append(course.ljust(name_w) + "".join(str(trend.count(course, d)).rjust(w)
                                                    for d, w in zip(trend.dates, widths)))
    lines.append("Total".ljust(name_w) + "".join(str(trend.total(d)).rjust(w) for d, w in zip(trend.dates, widths)))
    return "\n".join(lines)


def _group(problems, tz: tzinfo) -> list:
    grouped: dict = {}
    for a in problems:
        grouped.setdefault(a.course, []).append(a)
    return list(grouped.items())


def _due(a: NormalizedAssignment, tz: tzinfo) -> str:
    return _fmt(a.due.astimezone(tz).date()) if a.due else "no due date"


def render_email(ctx: EmailContext) -> EmailContent:
    kinds = [problem_kind(a) for a in ctx.problems]
    summary = _summary(kinds.count(KIND_MISSING), kinds.count(KIND_ZERO), ctx.trend)
    subject = f"{ctx.student_name}: assignment check-in, {ctx.run_date:%a %b} {ctx.run_date.day}"
    footer_text, emphasized = token_footer(ctx.token_days_remaining)
    groups = _group(ctx.problems, ctx.tz)

    items_html = ""
    items_text = ""
    if groups:
        items_html = '<h3 style="margin:20px 0 4px;">Today\'s items</h3>'
        items_text = "\nToday's items\n"
        for course, items in groups:
            items_html += f'<p style="margin:12px 0 4px;font-weight:600;">{_html.escape(course)}</p><ul style="margin:0;padding-left:20px;">'
            items_text += f"\n{course}\n"
            for a in items:
                kind = problem_kind(a) or ""
                items_html += (f"<li>{_html.escape(a.name)} &mdash; due {_html.escape(_due(a, ctx.tz))} "
                               f"&mdash; <b>{kind}</b></li>")
                items_text += f"  - {a.name} - due {_due(a, ctx.tz)} - {kind}\n"
            items_html += "</ul>"

    footer_style = "margin-top:24px;font-size:12px;" + ("font-weight:700;color:#9a6700;" if emphasized else "opacity:0.7;")
    footer_html = f'<p style="{footer_style}">{_html.escape(footer_text)}</p>' if footer_text else ""

    html = (
        '<!doctype html><html><head><meta charset="utf-8"><meta name="color-scheme" content="light dark"></head>'
        '<body style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;font-size:15px;line-height:1.4;">'
        f'<p style="margin:0 0 16px;">{_html.escape(summary)}</p>'
        f"{_grid_html(ctx.trend)}{items_html}"
        f'<p style="margin:24px 0;"><a href="{_html.escape(ctx.tab_url, quote=True)}" '
        'style="display:inline-block;padding:10px 16px;background:#466eb4;color:#ffffff;text-decoration:none;'
        f'border-radius:6px;">Open the full list (tab {_html.escape(ctx.tab_title)})</a></p>'
        f'<p style="font-size:12px;opacity:0.7;">Data from Infinite Campus, run {ctx.run_date.isoformat()}.</p>'
        f"{footer_html}</body></html>")

    text = (f"{summary}\n\n{_grid_text(ctx.trend)}\n{items_text}\n"
            f"Full list (tab {ctx.tab_title}): {ctx.tab_url}\n\n"
            f"Data from Infinite Campus, run {ctx.run_date.isoformat()}.\n"
            + (f"{footer_text}\n" if footer_text else ""))
    return EmailContent(subject, html, text)
```

- [ ] **Step 4: Run to verify pass** — `.venv/bin/python -m pytest tests/ic_tracker/test_report_email.py -q`. If `test_no_percentages_or_red_in_email` fails because of a legitimate `%`, adjust the test's allowed substrings, not the email.
- [ ] **Step 5: Commit** [commit-gated]

---

### Task 7: Google auth and token lifecycle

**Files:**
- Create: `src/ic_tracker/google/__init__.py`, `src/ic_tracker/google/auth.py`, `tests/ic_tracker/test_google_auth.py`

**Interfaces:**
- Consumes: `Settings` (cache_dir, op refs).
- Produces: `SCOPES`; `AuthExpiredError`, `ClientConfigError`; `token_days_remaining(issued_at, now, ttl_days) -> int|None`; `write_private(path, text)`; `load_token_issued_at(settings) -> datetime|None`; `read_client_from_1password(settings, run=subprocess.run) -> dict`; `authorize(settings, *, flow_runner=default_flow_runner, op_run=subprocess.run, now=None) -> datetime`; `get_credentials(settings, *, credentials_factory=None, request_factory=None)`; `build_services(creds) -> tuple(drive, sheets, gmail)`.

- [ ] **Step 1: Write failing tests**

`tests/ic_tracker/test_google_auth.py`:
```python
import json
import stat
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest
from google.auth.exceptions import RefreshError

from ic_tracker.config import load_settings
from ic_tracker.google import auth

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def settings(tmp_path):
    return load_settings({"IC_BASE_URL": "u", "IC_USERNAME": "u", "IC_PASSWORD": "p", "IC_DISTRICT": "d",
                          "TRACKER_EMAIL_TO": "a@x.com", "TRACKER_CACHE_DIR": str(tmp_path)})


@pytest.mark.parametrize("age_days,ttl,expected", [(0, 7, 7), (6, 7, 1), (7, 7, 0), (9, 7, -2), (3, None, None)])
def test_token_days_remaining(age_days, ttl, expected):
    assert auth.token_days_remaining(NOW - timedelta(days=age_days), NOW, ttl) == expected


def test_days_remaining_counts_whole_days_only():
    assert auth.token_days_remaining(NOW - timedelta(days=6, hours=23), NOW, 7) == 1
    assert auth.token_days_remaining(NOW - timedelta(days=7, hours=1), NOW, 7) == 0


def test_write_private_sets_mode_600(tmp_path):
    path = tmp_path / "sub" / "f.json"
    auth.write_private(path, "{}")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    auth.write_private(path, "{}")  # overwrite keeps the mode
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


class FakeOp:
    def __init__(self):
        self.calls = []

    def __call__(self, args, **kw):
        self.calls.append(args[-1])
        return NS(stdout="id-from-op\n" if args[-1].endswith("client_id") else "secret-from-op\n")


def test_read_client_from_1password(settings):
    op = FakeOp()
    cfg = auth.read_client_from_1password(settings, run=op)
    assert cfg["installed"]["client_id"] == "id-from-op"
    assert cfg["installed"]["client_secret"] == "secret-from-op"
    assert op.calls == [settings.op_client_id_ref, settings.op_client_secret_ref]


class FakeCreds:
    def to_json(self):
        return json.dumps({"refresh_token": "r", "client_id": "i"})


def test_authorize_uses_cache_when_present_and_stores_token(settings):
    auth.write_private(settings.cache_dir / "google_client.json", json.dumps({"installed": {"client_id": "cached"}}))
    op = FakeOp()
    seen = []
    issued = auth.authorize(settings, flow_runner=lambda cfg, scopes: (seen.append(cfg), FakeCreds())[1],
                            op_run=op, now=NOW)
    assert issued == NOW and op.calls == [] and seen[0]["installed"]["client_id"] == "cached"
    token = json.loads((settings.cache_dir / "google_token.json").read_text())
    assert token["issued_at"] == NOW.isoformat() and token["authorized_user"]["refresh_token"] == "r"
    assert stat.S_IMODE((settings.cache_dir / "google_token.json").stat().st_mode) == 0o600
    assert auth.load_token_issued_at(settings) == NOW


def test_authorize_without_cache_reads_1password_and_caches_after_success(settings):
    op = FakeOp()
    auth.authorize(settings, flow_runner=lambda cfg, scopes: FakeCreds(), op_run=op, now=NOW)
    assert len(op.calls) == 2
    assert json.loads((settings.cache_dir / "google_client.json").read_text())["installed"]["client_id"] == "id-from-op"


def test_authorize_failure_does_not_cache_client_or_token(settings):
    def boom(cfg, scopes):
        raise RuntimeError("user closed the browser")
    with pytest.raises(RuntimeError):
        auth.authorize(settings, flow_runner=boom, op_run=FakeOp(), now=NOW)
    assert not (settings.cache_dir / "google_client.json").exists()
    assert not (settings.cache_dir / "google_token.json").exists()


def test_authorize_retries_once_with_fresh_client_on_invalid_client(settings):
    auth.write_private(settings.cache_dir / "google_client.json", json.dumps({"installed": {"client_id": "stale"}}))
    calls = []

    def flow(cfg, scopes):
        calls.append(cfg["installed"]["client_id"])
        if cfg["installed"]["client_id"] == "stale":
            raise RuntimeError("invalid_client: Unauthorized")
        return FakeCreds()

    auth.authorize(settings, flow_runner=flow, op_run=FakeOp(), now=NOW)
    assert calls == ["stale", "id-from-op"]
    assert json.loads((settings.cache_dir / "google_client.json").read_text())["installed"]["client_id"] == "id-from-op"


def test_get_credentials_without_token_asks_for_auth(settings):
    with pytest.raises(auth.AuthExpiredError) as err:
        auth.get_credentials(settings)
    assert "ic-tracker auth" in str(err.value)


def test_get_credentials_refresh_failure_becomes_auth_expired(settings):
    auth.write_private(settings.cache_dir / "google_token.json",
                       json.dumps({"authorized_user": {"refresh_token": "r"}, "issued_at": NOW.isoformat()}))

    class Dead:
        valid = False

        def refresh(self, request):
            raise RefreshError("invalid_grant: Token has been expired or revoked.")

    with pytest.raises(auth.AuthExpiredError) as err:
        auth.get_credentials(settings, credentials_factory=lambda info: Dead(), request_factory=object)
    assert "ic-tracker auth" in str(err.value)


def test_get_credentials_refreshes_when_not_valid(settings):
    auth.write_private(settings.cache_dir / "google_token.json",
                       json.dumps({"authorized_user": {"refresh_token": "r"}, "issued_at": NOW.isoformat()}))

    class Ok:
        valid = False
        refreshed = False

        def refresh(self, request):
            self.refreshed = True

    creds = Ok()
    assert auth.get_credentials(settings, credentials_factory=lambda info: creds, request_factory=object) is creds
    assert creds.refreshed
```

- [ ] **Step 2: Run to verify failure** — `ModuleNotFoundError: ic_tracker.google`.

- [ ] **Step 3: Implement**

`src/ic_tracker/google/auth.py`:
```python
"""Google OAuth: client config, token cache with issue time, credentials, API services."""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ic_tracker.config import Settings

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.send",
]
_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
_TOKEN_URI = "https://oauth2.googleapis.com/token"


class AuthExpiredError(Exception):
    """The cached Google token is missing, expired or revoked; run `ic-tracker auth`."""


class ClientConfigError(Exception):
    """The OAuth client id/secret could not be read."""


def token_days_remaining(issued_at: datetime, now: datetime, ttl_days: Optional[int]) -> Optional[int]:
    if ttl_days is None:
        return None
    return ttl_days - (now - issued_at).days


def write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(text)
    os.chmod(path, 0o600)


def _client_path(settings: Settings) -> Path:
    return settings.cache_dir / "google_client.json"


def _token_path(settings: Settings) -> Path:
    return settings.cache_dir / "google_token.json"


def _read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def load_token_issued_at(settings: Settings) -> Optional[datetime]:
    data = _read_json(_token_path(settings))
    return datetime.fromisoformat(data["issued_at"]) if data and "issued_at" in data else None


def read_client_from_1password(settings: Settings, run=subprocess.run) -> dict:
    def read(ref: str) -> str:
        try:
            return run(["op", "read", ref], capture_output=True, text=True, check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError) as error:
            raise ClientConfigError(f"Could not read {ref} from 1Password: {error}") from error

    return {"installed": {
        "client_id": read(settings.op_client_id_ref),
        "client_secret": read(settings.op_client_secret_ref),
        "auth_uri": _AUTH_URI, "token_uri": _TOKEN_URI, "redirect_uris": ["http://localhost"]}}


def default_flow_runner(client_config: dict, scopes: list):
    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_config(client_config, scopes)
    return flow.run_local_server(port=0, prompt="consent", access_type="offline")


def _is_client_error(error: Exception) -> bool:
    return "invalid_client" in str(error)


def authorize(settings: Settings, *, flow_runner=default_flow_runner, op_run=subprocess.run,
              now: Optional[datetime] = None) -> datetime:
    """One-time browser consent. Caches the client and token only after the flow succeeds."""
    now = now or datetime.now(timezone.utc)
    client = _read_json(_client_path(settings))
    if client is not None:
        try:
            creds = flow_runner(client, SCOPES)
        except Exception as error:
            if not _is_client_error(error):
                raise
            client = read_client_from_1password(settings, op_run)
            creds = flow_runner(client, SCOPES)
    else:
        client = read_client_from_1password(settings, op_run)
        creds = flow_runner(client, SCOPES)
    write_private(_client_path(settings), json.dumps(client))
    write_private(_token_path(settings),
                  json.dumps({"authorized_user": json.loads(creds.to_json()), "issued_at": now.isoformat()}))
    return now


def get_credentials(settings: Settings, *, credentials_factory=None, request_factory=None):
    stored = _read_json(_token_path(settings))
    if not stored or "authorized_user" not in stored:
        raise AuthExpiredError("No Google token is cached. Run: ic-tracker auth")
    if credentials_factory is None:
        from google.oauth2.credentials import Credentials
        credentials_factory = lambda info: Credentials.from_authorized_user_info(info, SCOPES)  # noqa: E731
    if request_factory is None:
        from google.auth.transport.requests import Request as request_factory
    creds = credentials_factory(stored["authorized_user"])
    if not creds.valid:
        from google.auth.exceptions import RefreshError
        try:
            creds.refresh(request_factory())
        except RefreshError as error:
            raise AuthExpiredError(f"Google rejected the cached token ({error}). Run: ic-tracker auth") from error
    return creds


def build_services(creds):
    from googleapiclient.discovery import build
    return (build("drive", "v3", credentials=creds, cache_discovery=False),
            build("sheets", "v4", credentials=creds, cache_discovery=False),
            build("gmail", "v1", credentials=creds, cache_discovery=False))
```

- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** [commit-gated]

---

### Task 8: Sheets gateway

**Files:**
- Create: `src/ic_tracker/google/sheets.py`, `tests/ic_tracker/fakes.py` (FakeSheetsService), `tests/ic_tracker/test_google_sheets.py`

**Interfaces:**
- Consumes: `TabData`, `HistoryRow`.
- Produces: `HISTORY_TITLE="History"`, `HISTORY_HEADER`; `tab_url(spreadsheet_id, gid) -> str`; `class SheetsGateway(service)` with `tab_titles(sid) -> list[str]`, `write_tab(sid, title, tab) -> int`, `read_tab_values(sid, title) -> list[list[str]]`, `read_history(sid) -> list[HistoryRow]`, `upsert_history(sid, rows: list[HistoryRow]) -> None`.

- [ ] **Step 1: Write the fake and failing tests**

`tests/ic_tracker/fakes.py`:
```python
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
        self.batches = []         # every batchUpdate request body's requests
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
        return self

    def update(self, spreadsheetId, range, valueInputOption, body):
        def run():
            title, row = self._parse(range)
            self.rows[title] = self.rows[title][:row] + [list(r) for r in body["values"]]
            self.last_input_option = valueInputOption
            return {}
        return _Req(run)

    def clear(self, spreadsheetId, range, body=None):
        def run():
            title, row = self._parse(range)
            self.rows[title] = self.rows[title][:row]
            return {}
        return _Req(run)

    def get_values(self, spreadsheetId, range):
        def run():
            title, row = self._parse(range)
            return {"values": [[str(c) for c in r] for r in self.rows[title][row:]]}
        return _Req(run)
```
The Sheets API names both `spreadsheets().get` and `spreadsheets().values().get`. Since the fake returns itself from both, the gateway's `values().get(...)` must reach `get_values`. Handle it by making `values()` return a small adapter:
```python
    def values(self):
        outer = self

        class _Values:
            def get(self, spreadsheetId, range):
                return outer.get_values(spreadsheetId, range)
            update = staticmethod(outer.update)
            clear = staticmethod(outer.clear)
        return _Values()
```
(use this version of `values()` in the file, replacing the `return self` one).

`tests/ic_tracker/test_google_sheets.py`:
```python
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
```

- [ ] **Step 2: Run to verify failure** — `ModuleNotFoundError: ic_tracker.google.sheets`.

- [ ] **Step 3: Implement**

`src/ic_tracker/google/sheets.py`:
```python
"""Google Sheets access: dated tabs and the History tab."""
from __future__ import annotations

import logging
from datetime import date

from ic_tracker.analysis import HistoryRow
from ic_tracker.report.sheet import TabData

logger = logging.getLogger(__name__)

HISTORY_TITLE = "History"
HISTORY_HEADER = ["Date", "Class", "Assignments", "Missing", "Zeros", "Needs attention"]
_RED = {"red": 0.957, "green": 0.8, "blue": 0.8}


def _quote(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


def tab_url(spreadsheet_id: str, gid: int) -> str:
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit#gid={gid}"


def _grid(gid: int, row0: int = 0, row1: int | None = None, col0: int = 0, col1: int | None = None) -> dict:
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

    def _add_tab(self, sid: str, title: str, index: int | None = None) -> int:
        props = {"title": title}
        if index is not None:
            props["index"] = index
        reply = self._batch(sid, [{"addSheet": {"properties": props}}])
        return reply["replies"][0]["addSheet"]["properties"]["sheetId"]

    def tab_titles(self, sid: str) -> list:
        return list(self._tabs(sid))

    def write_tab(self, sid: str, title: str, tab: TabData) -> int:
        tabs = self._tabs(sid)
        existing = title in tabs
        if existing:
            gid = tabs[title]
            self._svc.spreadsheets().values().clear(spreadsheetId=sid, range=_quote(title), body={}).execute()
        else:
            gid = self._add_tab(sid, title, index=0)
        self._svc.spreadsheets().values().update(
            spreadsheetId=sid, range=f"{_quote(title)}!A1", valueInputOption="USER_ENTERED",
            body={"values": tab.values}).execute()
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
        if HISTORY_TITLE not in self._tabs(sid):
            self._add_tab(sid, HISTORY_TITLE)
        replaced = {r.run_date for r in new_rows}
        kept = [r for r in self.read_history(sid) if r.run_date not in replaced]
        merged = sorted(kept + list(new_rows), key=lambda r: (r.run_date, r.course.casefold()))
        values = [HISTORY_HEADER] + [[r.run_date.isoformat(), r.course, r.assignments, r.missing, r.zeros,
                                      r.needs_attention] for r in merged]
        self._svc.spreadsheets().values().clear(spreadsheetId=sid, range=HISTORY_TITLE, body={}).execute()
        self._svc.spreadsheets().values().update(
            spreadsheetId=sid, range=f"{HISTORY_TITLE}!A1", valueInputOption="RAW", body={"values": values}).execute()
```

- [ ] **Step 4: Run to verify pass.** If the fake's `_parse` regex mishandles a range form, fix the fake (it is test code), not the gateway.
- [ ] **Step 5: Commit** [commit-gated]

---

### Task 9: Drive gateway

**Files:**
- Create: `src/ic_tracker/google/drive.py`, `tests/ic_tracker/test_google_drive.py`

**Interfaces:**
- Produces: constants `FOLDER_MIME`, `SHEET_MIME`, `XLSX_MIME`; `class DriveNotFoundError(Exception)`; `class DriveGateway(service)` with `find_folder(path) -> str`, `find_file(name, parent_id, mime) -> dict | None`, `convert_xlsx_to_sheet(xlsx_id, folder_id, title) -> str`.

- [ ] **Step 1: Write failing tests**

`tests/ic_tracker/test_google_drive.py`:
```python
import pytest

from ic_tracker.google.drive import (FOLDER_MIME, SHEET_MIME, XLSX_MIME, DriveGateway, DriveNotFoundError)


class _Req:
    def __init__(self, value):
        self._v = value

    def execute(self):
        return self._v


class FakeDrive:
    def __init__(self, tree):
        self.tree = tree            # query substring -> list of file dicts
        self.queries = []
        self.created = None
        self.media_bytes = b"xlsx-bytes"

    def files(self):
        return self

    def list(self, q, **kw):
        self.queries.append(q)
        for needle, files in self.tree.items():
            if needle in q:
                return _Req({"files": files})
        return _Req({"files": []})

    def get_media(self, fileId):
        self.fetched = fileId
        return _Req(self.media_bytes)

    def create(self, body, media_body, fields):
        self.created = (body, media_body)
        return _Req({"id": "NEW"})


def test_find_folder_walks_path_from_root():
    drive = FakeDrive({"name='Kids'": [{"id": "K"}], "name='Alex'": [{"id": "KK"}]})
    assert DriveGateway(drive).find_folder("Kids/Alex") == "KK"
    assert "'root' in parents" in drive.queries[0]
    assert "'K' in parents" in drive.queries[1]
    assert FOLDER_MIME in drive.queries[0] and "trashed=false" in drive.queries[0]


def test_find_folder_missing_raises():
    with pytest.raises(DriveNotFoundError) as err:
        DriveGateway(FakeDrive({})).find_folder("Kids/Alex")
    assert "Kids/Alex" in str(err.value) or "Kids" in str(err.value)


def test_find_file_escapes_quotes_and_returns_first_or_none():
    drive = FakeDrive({"name='Kai\\'s": [{"id": "F1", "name": "x"}]})
    gw = DriveGateway(drive)
    assert gw.find_file("Kai's", "P", SHEET_MIME)["id"] == "F1"
    assert gw.find_file("Other", "P", SHEET_MIME) is None


def test_convert_xlsx_downloads_then_uploads_as_google_sheet():
    drive = FakeDrive({})
    new_id = DriveGateway(drive).convert_xlsx_to_sheet("XLSX", "FOLDER", "Assignments Tracker")
    body, media = drive.created
    assert new_id == "NEW" and drive.fetched == "XLSX"
    assert body == {"name": "Assignments Tracker", "mimeType": SHEET_MIME, "parents": ["FOLDER"]}
    assert media.mimetype() == XLSX_MIME
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement**

`src/ic_tracker/google/drive.py`:
```python
"""Google Drive access: locate the folder and tracker file, convert the xlsx once."""
from __future__ import annotations

import io
from typing import Optional

FOLDER_MIME = "application/vnd.google-apps.folder"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class DriveNotFoundError(Exception):
    """A folder or file the tracker needs does not exist."""


def _esc(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


class DriveGateway:
    def __init__(self, service):
        self._svc = service

    def _list(self, query: str) -> list:
        resp = self._svc.files().list(q=query, fields="files(id,name,mimeType)", pageSize=100,
                                      spaces="drive").execute()
        return resp.get("files", [])

    def find_folder(self, path: str) -> str:
        parent = "root"
        for part in [p for p in path.strip("/").split("/") if p]:
            found = self._list(f"name='{_esc(part)}' and mimeType='{FOLDER_MIME}' "
                               f"and '{parent}' in parents and trashed=false")
            if not found:
                raise DriveNotFoundError(f"Drive folder not found: {path} (missing '{part}')")
            parent = found[0]["id"]
        return parent

    def find_file(self, name: str, parent_id: str, mime: str) -> Optional[dict]:
        found = self._list(f"name='{_esc(name)}' and mimeType='{mime}' and '{parent_id}' in parents and trashed=false")
        return found[0] if found else None

    def convert_xlsx_to_sheet(self, xlsx_id: str, folder_id: str, title: str) -> str:
        from googleapiclient.http import MediaIoBaseUpload
        content = self._svc.files().get_media(fileId=xlsx_id).execute()
        media = MediaIoBaseUpload(io.BytesIO(content), mimetype=XLSX_MIME, resumable=False)
        created = self._svc.files().create(
            body={"name": title, "mimeType": SHEET_MIME, "parents": [folder_id]},
            media_body=media, fields="id").execute()
        return created["id"]
```

- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** [commit-gated]

---

### Task 10: Gmail gateway and alerts

**Files:**
- Create: `src/ic_tracker/google/gmail.py`, `src/ic_tracker/alert.py`, `tests/ic_tracker/test_gmail_alert.py`

**Interfaces:**
- Produces: `build_raw_message(to, cc, subject, text, html) -> str` (base64url); `class GmailGateway(service)` with `send(to, cc, subject, text, html) -> str` (message id); `notify(title, message, run=subprocess.run) -> None`; `report_failure(settings, title, message, *, notify_fn=notify, email_fn=None) -> None`.

- [ ] **Step 1: Write failing tests**

`tests/ic_tracker/test_gmail_alert.py`:
```python
import base64
import email
from types import SimpleNamespace as NS

from ic_tracker.alert import notify, report_failure
from ic_tracker.config import load_settings
from ic_tracker.google.gmail import GmailGateway, build_raw_message


def parse(raw):
    return email.message_from_bytes(base64.urlsafe_b64decode(raw))


def test_message_has_recipients_subject_and_both_parts():
    msg = parse(build_raw_message(("a@x.com",), ("b@x.com", "c@x.com"), "Alex: check-in", "plain", "<p>html</p>"))
    assert msg["To"] == "a@x.com" and msg["Cc"] == "b@x.com, c@x.com"
    assert msg["Subject"] == "Alex: check-in"
    types = [p.get_content_type() for p in msg.walk() if not p.is_multipart()]
    assert types == ["text/plain", "text/html"]


def test_no_cc_header_when_cc_empty_and_non_ascii_subject_survives():
    msg = parse(build_raw_message(("a@x.com",), (), "Café check-in", "t", "<p>h</p>"))
    assert msg["Cc"] is None
    assert str(email.header.make_header(email.header.decode_header(msg["Subject"]))) == "Café check-in"


class FakeGmail:
    def __init__(self):
        self.sent = None

    def users(self):
        return self

    def messages(self):
        return self

    def send(self, userId, body):
        self.sent = (userId, body)
        return NS(execute=lambda: {"id": "MSG1"})


def test_gateway_sends_as_me():
    svc = FakeGmail()
    assert GmailGateway(svc).send(("a@x.com",), (), "s", "t", "<p>h</p>") == "MSG1"
    assert svc.sent[0] == "me" and "raw" in svc.sent[1]


def test_notify_escapes_quotes_and_never_raises():
    calls = []
    notify('Tracker "failed"', 'say "hi"', run=lambda args, **kw: calls.append(args))
    assert calls[0][0] == "osascript"
    assert '\\"failed\\"' in calls[0][2] and '\\"hi\\"' in calls[0][2]

    def boom(args, **kw):
        raise FileNotFoundError("osascript")
    notify("t", "m", run=boom)  # must not raise


def _settings(alert_to=""):
    return load_settings({"IC_BASE_URL": "u", "IC_USERNAME": "u", "IC_PASSWORD": "p", "IC_DISTRICT": "d",
                          "TRACKER_EMAIL_TO": "a@x.com", "TRACKER_ALERT_TO": alert_to})


def test_report_failure_notifies_and_emails_when_alert_to_set():
    notes, emails = [], []
    report_failure(_settings("me@x.com"), "T", "M", notify_fn=lambda t, m: notes.append((t, m)),
                   email_fn=lambda to, subject, body: emails.append((to, subject, body)))
    assert notes == [("T", "M")] and emails == [(("me@x.com",), "T", "M")]


def test_report_failure_skips_email_without_alert_to_and_swallows_email_errors():
    notes = []
    report_failure(_settings(), "T", "M", notify_fn=lambda t, m: notes.append(t), email_fn=lambda *a: 1 / 0)
    assert notes == ["T"]

    def broken(*a):
        raise RuntimeError("gmail down")
    report_failure(_settings("me@x.com"), "T", "M", notify_fn=lambda t, m: None, email_fn=broken)  # no raise
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement**

`src/ic_tracker/google/gmail.py`:
```python
"""Gmail sending."""
from __future__ import annotations

import base64
from email.message import EmailMessage


def build_raw_message(to, cc, subject: str, text: str, html: str) -> str:
    message = EmailMessage()
    message["To"] = ", ".join(to)
    if cc:
        message["Cc"] = ", ".join(cc)
    message["Subject"] = subject
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    return base64.urlsafe_b64encode(message.as_bytes()).decode()


class GmailGateway:
    def __init__(self, service):
        self._svc = service

    def send(self, to, cc, subject: str, text: str, html: str) -> str:
        raw = build_raw_message(to, cc, subject, text, html)
        sent = self._svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        return sent["id"]
```
`src/ic_tracker/alert.py`:
```python
"""Failure alerts: macOS notification always, email to TRACKER_ALERT_TO when possible."""
from __future__ import annotations

import logging
import subprocess
from typing import Callable, Optional

from ic_tracker.config import Settings

logger = logging.getLogger(__name__)


def _applescript_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def notify(title: str, message: str, run=subprocess.run) -> None:
    script = f"display notification {_applescript_quote(message)} with title {_applescript_quote(title)}"
    try:
        run(["osascript", "-e", script], check=False, capture_output=True)
    except Exception as error:  # a failed notification must never mask the original error
        logger.warning("Could not show notification: %s", error)


def report_failure(settings: Settings, title: str, message: str, *, notify_fn: Callable = notify,
                   email_fn: Optional[Callable] = None) -> None:
    logger.error("%s: %s", title, message)
    notify_fn(title, message)
    if settings.alert_to and email_fn is not None:
        try:
            email_fn(settings.alert_to, title, message)
        except Exception as error:
            logger.warning("Could not send failure email: %s", error)
```

- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** [commit-gated]

---

### Task 11: History backfill and migrate

**Files:**
- Create: `src/ic_tracker/backfill.py`, `tests/ic_tracker/test_backfill.py`

**Interfaces:**
- Consumes: `HistoryRow`, `Settings`, `DriveGateway` (`find_folder`, `find_file`, `convert_xlsx_to_sheet`), `SheetsGateway` (`tab_titles`, `read_tab_values`, `upsert_history`), constants `SHEET_MIME`, `XLSX_MIME`.
- Produces: `parse_tab_date(title) -> date | None`; `history_from_tab(run_date, values, excluded_prefixes) -> list[HistoryRow]`; `@dataclass(frozen=True) MigrationResult(spreadsheet_id:str, converted:bool, dates:list[date])`; `migrate(settings, drive, sheets) -> MigrationResult`; `class MigrationError(Exception)`.

- [ ] **Step 1: Write failing tests**

`tests/ic_tracker/test_backfill.py`:
```python
from datetime import date

import pytest

from ic_tracker.backfill import MigrationError, history_from_tab, migrate, parse_tab_date
from ic_tracker.config import load_settings
from ic_tracker.google.drive import SHEET_MIME, XLSX_MIME

HEADER = ["Class", "Due Date", "Assignment", "Score (raw)", "Earned", "Possible", "Percent", "Missing", "Zero",
          "Status", "Comment", "", "Class", "Assignments", "Missing", "Zeros (not missing)", "Needs attention"]


def row(course, missing="", zero="", stats=()):
    return [course, "2026-09-01", "A", "", "", "", "", missing, zero, "x", ""] + (["", *stats] if stats else [])


def test_parse_tab_date():
    assert parse_tab_date("2026-10-11") == date(2026, 10, 11)
    for bad in ("History", "2026-13-40", "Sheet1", "2026-10-1"):
        assert parse_tab_date(bad) is None


def test_history_from_tab_recomputes_counts_from_flags_not_the_stats_block():
    values = [HEADER,
              row("Math", stats=("Math", 99, 99, 99, 99)),
              row("Math", missing="Y", zero="Y"),
              row("Math", zero="Y"),
              row("Art"),
              row("Seminar 12", missing="Y", zero="Y"),
              ["", "", "", "", "", "", "", "", "", "", "", "", "Total", 5, 1, 1, 2]]
    rows = history_from_tab(date(2026, 10, 11), values, ("Seminar",))
    by = {r.course: r for r in rows}
    assert set(by) == {"Math", "Art"}
    assert (by["Math"].assignments, by["Math"].missing, by["Math"].zeros) == (3, 1, 1)
    assert (by["Art"].assignments, by["Art"].needs_attention) == (1, 0)
    assert all(r.run_date == date(2026, 10, 11) for r in rows)


def test_history_from_empty_or_headerless_tab_is_empty():
    assert history_from_tab(date(2026, 10, 11), [], ()) == []
    assert history_from_tab(date(2026, 10, 11), [["nothing", "useful"]], ()) == []


class FakeDrive:
    def __init__(self, sheet=None, xlsx=None):
        self.sheet, self.xlsx, self.converted = sheet, xlsx, []

    def find_folder(self, path):
        return "FOLDER"

    def find_file(self, name, parent, mime):
        return {SHEET_MIME: self.sheet, XLSX_MIME: self.xlsx}[mime]

    def convert_xlsx_to_sheet(self, xlsx_id, folder_id, title):
        self.converted.append((xlsx_id, folder_id, title))
        return "NEWSHEET"


class FakeSheets:
    def __init__(self, tabs):
        self.tabs, self.upserted = tabs, None

    def tab_titles(self, sid):
        return list(self.tabs)

    def read_tab_values(self, sid, title):
        return self.tabs[title]

    def upsert_history(self, sid, rows):
        self.upserted = rows


def settings():
    return load_settings({"IC_BASE_URL": "u", "IC_USERNAME": "u", "IC_PASSWORD": "p", "IC_DISTRICT": "d",
                          "TRACKER_EMAIL_TO": "a@x.com"})


def test_migrate_converts_xlsx_then_backfills_dated_tabs_only():
    drive = FakeDrive(sheet=None, xlsx={"id": "XLSX"})
    sheets = FakeSheets({"2026-10-11": [HEADER, row("Math", missing="Y", zero="Y")], "History": [["x"]]})
    result = migrate(settings(), drive, sheets)
    assert result.converted and result.spreadsheet_id == "NEWSHEET"
    assert drive.converted == [("XLSX", "FOLDER", "Assignments Tracker")]
    assert result.dates == [date(2026, 10, 11)]
    assert [(r.course, r.missing) for r in sheets.upserted] == [("Math", 1)]


def test_migrate_reuses_existing_sheet_without_converting_again():
    drive = FakeDrive(sheet={"id": "EXISTING"}, xlsx={"id": "XLSX"})
    result = migrate(settings(), drive, FakeSheets({}))
    assert not result.converted and result.spreadsheet_id == "EXISTING" and drive.converted == []


def test_migrate_without_sheet_or_xlsx_is_an_error():
    with pytest.raises(MigrationError):
        migrate(settings(), FakeDrive(), FakeSheets({}))
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement**

`src/ic_tracker/backfill.py`:
```python
"""One-time migration: convert the old xlsx and backfill History from its dated tabs."""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Optional

from ic_tracker.analysis import HistoryRow, exclude_courses  # noqa: F401  (exclude_courses used for naming parity)
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
    """Recompute per-class counts from the Class/Missing/Zero columns of an old tab (first 11 columns only)."""
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
            raise MigrationError(f"Neither a Google Sheet nor '{settings.sheet_name}.xlsx' found in {settings.drive_folder}")
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
```
(Remove the unused `exclude_courses` import when writing the file; it is shown only to flag that the prefix rule matches `analysis.exclude_courses`.)

- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** [commit-gated]

---

### Task 12: Runner (orchestration and dry run)

**Files:**
- Create: `src/ic_tracker/runner.py`, `tests/ic_tracker/test_runner.py`

**Interfaces:**
- Consumes: everything above. Sheets-like object needs `write_tab`, `upsert_history`, `read_history`; gmail-like needs `send(to, cc, subject, text, html)`.
- Produces: `NoDataError`; `@dataclass(frozen=True) Prepared(assignments, counts, problems, tab)`; `prepare(settings, data, tz) -> Prepared`; `@dataclass(frozen=True) RunResult(tab_title, tab_url, needs_attention, recipients)`; `run_report(*, settings, data, run_date, spreadsheet_id, sheets, gmail, token_days_remaining) -> RunResult`; `write_dry_run(*, settings, data, run_date, out_dir) -> list[Path]`.

- [ ] **Step 1: Write failing tests**

`tests/ic_tracker/test_runner.py`:
```python
from datetime import date

import pytest

from ic_tracker.analysis import HistoryRow
from ic_tracker.config import load_settings
from ic_tracker.ic.source import FetchResult
from ic_tracker.runner import NoDataError, prepare, run_report, write_dry_run
from tests.ic_tracker.builders import make_assignment, make_missing, make_zero

D = date(2026, 10, 15)


def settings(**env):
    base = {"IC_BASE_URL": "u", "IC_USERNAME": "u", "IC_PASSWORD": "p", "IC_DISTRICT": "d",
            "TRACKER_EMAIL_TO": "me@x.com", "TRACKER_EMAIL_CC": "cc@x.com"}
    return load_settings({**base, **env})


def data(items):
    return FetchResult("Alex", "S1", "2026-08-19", "2026-12-18", items)


class FakeSheets:
    def __init__(self, log, fail_write=False):
        self.log, self.fail_write, self.history = log, fail_write, []

    def write_tab(self, sid, title, tab):
        self.log.append("write_tab")
        if self.fail_write:
            raise RuntimeError("sheets down")
        self.tab = (title, tab)
        return 42

    def upsert_history(self, sid, rows):
        self.log.append("upsert_history")
        self.history = list(rows)

    def read_history(self, sid):
        self.log.append("read_history")
        return self.history


class FakeGmail:
    def __init__(self, log, fail=False):
        self.log, self.fail, self.sent = log, fail, None

    def send(self, to, cc, subject, text, html):
        self.log.append("send")
        if self.fail:
            raise RuntimeError("gmail down")
        self.sent = (to, cc, subject, text, html)
        return "id"


ITEMS = [make_missing(course="Math", name="W"), make_zero(course="Math", name="Q"), make_assignment(course="Art"),
         make_assignment(course="Seminar 1")]


def go(items=ITEMS, log=None, sheets=None, gmail=None, days=5):
    log = log if log is not None else []
    sheets = sheets or FakeSheets(log)
    gmail = gmail or FakeGmail(log)
    result = run_report(settings=settings(), data=data(items), run_date=D, spreadsheet_id="S", sheets=sheets,
                        gmail=gmail, token_days_remaining=days)
    return result, sheets, gmail, log


def test_prepare_excludes_sorts_and_collects_problems():
    prep = prepare(settings(), data(ITEMS), __import__("zoneinfo").ZoneInfo("America/Denver"))
    assert [a.course for a in prep.assignments] == ["Art", "Math", "Math"]
    assert [c.course for c in prep.counts] == ["Art", "Math"]
    assert sorted(a.name for a in prep.problems) == ["Q", "W"]


def test_order_is_sheet_then_history_then_read_then_send():
    _, _, _, log = go()
    assert log == ["write_tab", "upsert_history", "read_history", "send"]


def test_email_uses_configured_recipients_and_tab_link_and_footer():
    result, sheets, gmail, _ = go()
    to, cc, subject, text, html = gmail.sent
    assert to == ("me@x.com",) and cc == ("cc@x.com",)
    assert subject == "Alex: assignment check-in, Thu Oct 15"
    assert "gid=42" in html and "gid=42" in text and "2026-10-15" in text
    assert "expires in 5 days" in text
    assert result.tab_title == "2026-10-15" and result.needs_attention == 2
    assert sheets.tab[0] == "2026-10-15"
    assert {r.course for r in sheets.history} == {"Art", "Math"}


def test_no_assignments_aborts_before_any_write():
    log = []
    with pytest.raises(NoDataError):
        go(items=[], log=log)
    assert log == []
    with pytest.raises(NoDataError):
        go(items=[make_assignment(course="Seminar 1")], log=log)  # everything excluded
    assert log == []


def test_sheet_failure_sends_no_email():
    log = []
    with pytest.raises(RuntimeError):
        go(log=log, sheets=FakeSheets(log, fail_write=True))
    assert "send" not in log


def test_email_failure_leaves_sheet_written_and_propagates():
    log = []
    with pytest.raises(RuntimeError):
        go(log=log, gmail=FakeGmail(log, fail=True))
    assert log == ["write_tab", "upsert_history", "read_history", "send"]


def test_dry_run_writes_files_and_touches_nothing_else(tmp_path):
    paths = write_dry_run(settings=settings(), data=data(ITEMS), run_date=D, out_dir=tmp_path)
    names = sorted(p.name for p in paths)
    assert names == ["email.html", "email.txt", "tab.tsv"]
    assert "Needs attention today: 2" in (tmp_path / "email.txt").read_text()
    assert (tmp_path / "tab.tsv").read_text().startswith("Class\tDue Date")
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement**

`src/ic_tracker/runner.py`:
```python
"""Orchestration: prepare data, write the Sheet, then send the email."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from ic_tracker.analysis import (ClassCounts, HistoryRow, build_trend, exclude_courses, problem_kind,
                                 sort_assignments, summarize_by_class)
from ic_tracker.config import Settings
from ic_tracker.google.sheets import tab_url
from ic_tracker.ic.source import FetchResult
from ic_tracker.model import NormalizedAssignment
from ic_tracker.report.email import EmailContext, render_email
from ic_tracker.report.sheet import TabData, build_tab


class NoDataError(Exception):
    """Infinite Campus returned nothing to report; nothing was written."""


@dataclass(frozen=True)
class Prepared:
    assignments: list
    counts: list
    problems: list
    tab: TabData


def prepare(settings: Settings, data: FetchResult, tz) -> Prepared:
    assignments = sort_assignments(exclude_courses(data.assignments, settings.exclude_courses))
    if not assignments:
        raise NoDataError("No assignments after filtering; refusing to overwrite today's tab with empty data.")
    counts = summarize_by_class(assignments)
    problems = [a for a in assignments if problem_kind(a)]
    return Prepared(assignments, counts, problems, build_tab(assignments, counts, tz))


@dataclass(frozen=True)
class RunResult:
    tab_title: str
    tab_url: str
    needs_attention: int
    recipients: tuple


def run_report(*, settings: Settings, data: FetchResult, run_date: date, spreadsheet_id: str, sheets, gmail,
               token_days_remaining: Optional[int]) -> RunResult:
    tz = ZoneInfo(settings.timezone)
    prep = prepare(settings, data, tz)
    title = run_date.isoformat()
    gid = sheets.write_tab(spreadsheet_id, title, prep.tab)
    sheets.upsert_history(spreadsheet_id, [HistoryRow.from_counts(run_date, c) for c in prep.counts])
    trend = build_trend(sheets.read_history(spreadsheet_id), run_date)
    url = tab_url(spreadsheet_id, gid)
    content = render_email(EmailContext(
        student_name=data.student_first_name, run_date=run_date, trend=trend, problems=prep.problems,
        tab_url=url, tab_title=title, token_days_remaining=token_days_remaining, tz=tz))
    gmail.send(settings.email_to, settings.email_cc, content.subject, content.text, content.html)
    return RunResult(title, url, len(prep.problems), settings.email_to + settings.email_cc)


def write_dry_run(*, settings: Settings, data: FetchResult, run_date: date, out_dir: Path) -> list:
    """Render the email and tab rows to files using only today's data. No Google calls."""
    tz = ZoneInfo(settings.timezone)
    prep = prepare(settings, data, tz)
    trend = build_trend([HistoryRow.from_counts(run_date, c) for c in prep.counts], run_date)
    content = render_email(EmailContext(
        student_name=data.student_first_name, run_date=run_date, trend=trend, problems=prep.problems,
        tab_url="https://docs.google.com/spreadsheets/d/DRY_RUN/edit#gid=0", tab_title=run_date.isoformat(),
        token_days_remaining=settings.token_ttl_days, tz=tz))
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {"email.html": content.html, "email.txt": content.text,
             "tab.tsv": "\n".join("\t".join(str(c) for c in row) for row in prep.tab.values) + "\n"}
    paths = []
    for name, text in files.items():
        path = out_dir / name
        path.write_text(text)
        paths.append(path)
    return paths
```

- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** [commit-gated]

---

### Task 13: CLI

**Files:**
- Create: `src/ic_tracker/cli.py`, `tests/ic_tracker/test_cli.py`

**Interfaces:**
- Produces: `build_parser() -> argparse.ArgumentParser` (subcommands `run [--student NAME] [--dry-run] [--out DIR] [--date YYYY-MM-DD]`, `auth`, `migrate`, `status`); `main(argv=None, *, handlers=None) -> int`. Exit codes: 0 success, 1 unexpected error, 2 auth expired, 3 no data, 4 configuration error, 5 student not found.

- [ ] **Step 1: Write failing tests**

`tests/ic_tracker/test_cli.py`:
```python
from datetime import date

import pytest

from ic_tracker import cli
from ic_tracker.config import ConfigError
from ic_tracker.google.auth import AuthExpiredError
from ic_tracker.ic.source import StudentNotFoundError
from ic_tracker.runner import NoDataError


def test_parser_run_options():
    args = cli.build_parser().parse_args(["run", "--student", "sam", "--dry-run", "--date", "2026-10-15"])
    assert (args.command, args.student, args.dry_run, args.date) == ("run", "sam", True, date(2026, 10, 15))


def test_parser_requires_a_command():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([])


@pytest.mark.parametrize("exc,code", [
    (AuthExpiredError("x"), 2), (NoDataError("x"), 3), (ConfigError("x"), 4),
    (StudentNotFoundError("x"), 5), (RuntimeError("x"), 1)])
def test_exit_codes_and_failure_reporting(exc, code):
    reported = []

    def boom(args):
        raise exc

    rc = cli.main(["status"], handlers={"status": boom}, reporter=lambda title, msg: reported.append((title, msg)))
    assert rc == code
    assert reported and "x" in reported[0][1]


def test_success_returns_zero_without_reporting():
    reported = []
    assert cli.main(["status"], handlers={"status": lambda a: 0}, reporter=lambda *a: reported.append(a)) == 0
    assert reported == []
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement**

`src/ic_tracker/cli.py`:
```python
"""Command line interface: run, auth, migrate, status."""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from ic_tracker.config import ConfigError, Settings, load_settings
from ic_tracker.google.auth import AuthExpiredError
from ic_tracker.ic.source import StudentNotFoundError
from ic_tracker.runner import NoDataError

logger = logging.getLogger("ic_tracker")


def _date(value: str) -> date:
    return date.fromisoformat(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ic-tracker", description="Daily Infinite Campus assignment report.")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="fetch assignments, update the Sheet, send the email")
    run.add_argument("--student", help="first name (default: TRACKER_STUDENT)")
    run.add_argument("--dry-run", action="store_true", help="render files only; no Google calls, no email")
    run.add_argument("--out", type=Path, help="dry-run output directory")
    run.add_argument("--date", type=_date, help="override the run date (YYYY-MM-DD)")
    sub.add_parser("auth", help="one-time Google consent; renews the cached token")
    sub.add_parser("migrate", help="convert the old xlsx to a Google Sheet and backfill History")
    sub.add_parser("status", help="show Google token age and days remaining")
    return parser


def _load_settings() -> Settings:
    from dotenv import load_dotenv, find_dotenv
    load_dotenv(find_dotenv(usecwd=True))
    return load_settings(os.environ)


def _services(settings: Settings):
    from ic_tracker.google.auth import build_services, get_credentials
    return build_services(get_credentials(settings))


def _cmd_run(args) -> int:
    from ic_tracker.google.auth import load_token_issued_at, token_days_remaining
    from ic_tracker.google.drive import SHEET_MIME, DriveGateway
    from ic_tracker.google.gmail import GmailGateway
    from ic_tracker.google.sheets import SheetsGateway
    from ic_tracker.ic.source import fetch
    from ic_tracker.runner import run_report, write_dry_run

    settings = _load_settings()
    if args.student:
        settings = Settings(**{**settings.__dict__, "student": args.student})
    run_date = args.date or datetime.now(ZoneInfo(settings.timezone)).date()
    data = asyncio.run(fetch(settings, run_date))
    if args.dry_run:
        out = args.out or settings.cache_dir / "dry-run"
        for path in write_dry_run(settings=settings, data=data, run_date=run_date, out_dir=out):
            print(path)
        return 0
    drive_svc, sheets_svc, gmail_svc = _services(settings)
    drive = DriveGateway(drive_svc)
    sheet = drive.find_file(settings.sheet_name, drive.find_folder(settings.drive_folder), SHEET_MIME)
    if sheet is None:
        raise ConfigError(f"Google Sheet '{settings.sheet_name}' not found in {settings.drive_folder}. Run: ic-tracker migrate")
    issued = load_token_issued_at(settings)
    days = token_days_remaining(issued, datetime.now(timezone.utc), settings.token_ttl_days) if issued else None
    result = run_report(settings=settings, data=data, run_date=run_date, spreadsheet_id=sheet["id"],
                        sheets=SheetsGateway(sheets_svc), gmail=GmailGateway(gmail_svc), token_days_remaining=days)
    print(f"Wrote tab {result.tab_title} ({result.needs_attention} need attention); emailed {', '.join(result.recipients)}")
    print(result.tab_url)
    return 0


def _cmd_auth(args) -> int:
    from ic_tracker.google.auth import authorize
    settings = _load_settings()
    issued = authorize(settings)
    if settings.token_ttl_days is None:
        print("Google token cached.")
    else:
        from datetime import timedelta
        expires = issued + timedelta(days=settings.token_ttl_days)
        print(f"Google token cached. It should work until about {expires.astimezone():%Y-%m-%d %H:%M} "
              f"({settings.token_ttl_days} days).")
    return 0


def _cmd_migrate(args) -> int:
    from ic_tracker.backfill import migrate
    from ic_tracker.google.drive import DriveGateway
    from ic_tracker.google.sheets import SheetsGateway
    settings = _load_settings()
    drive_svc, sheets_svc, _ = _services(settings)
    result = migrate(settings, DriveGateway(drive_svc), SheetsGateway(sheets_svc))
    action = "Converted xlsx to a new Google Sheet" if result.converted else "Found existing Google Sheet"
    print(f"{action}: https://docs.google.com/spreadsheets/d/{result.spreadsheet_id}")
    print("History backfilled for: " + (", ".join(d.isoformat() for d in result.dates) or "(no dated tabs)"))
    return 0


def _cmd_status(args) -> int:
    from ic_tracker.google.auth import load_token_issued_at, token_days_remaining
    settings = _load_settings()
    issued = load_token_issued_at(settings)
    if issued is None:
        print("No Google token cached. Run: ic-tracker auth")
        return 2
    days = token_days_remaining(issued, datetime.now(timezone.utc), settings.token_ttl_days)
    print(f"Token issued {issued.astimezone():%Y-%m-%d %H:%M}; "
          + ("no expiry configured." if days is None else f"{days} day(s) remaining."))
    return 0


_EXIT = ((AuthExpiredError, 2), (NoDataError, 3), (ConfigError, 4), (StudentNotFoundError, 5))


def _default_reporter(title: str, message: str) -> None:
    from ic_tracker.alert import notify
    notify(title, message)


def main(argv: Optional[list] = None, *, handlers: Optional[dict] = None,
         reporter: Callable = _default_reporter) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    table = {"run": _cmd_run, "auth": _cmd_auth, "migrate": _cmd_migrate, "status": _cmd_status}
    table.update(handlers or {})
    try:
        return table[args.command](args)
    except Exception as error:
        code = next((c for exc, c in _EXIT if isinstance(error, exc)), 1)
        logger.error("%s failed: %s", args.command, error, exc_info=code == 1)
        reporter(f"ic-tracker {args.command} failed", str(error))
        return code


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run to verify pass**, then `.venv/bin/ic-tracker --help` and `.venv/bin/ic-tracker run --help` show the commands.
- [ ] **Step 5: Commit** [commit-gated]

---

### Task 14: Scheduling, docs, cleanup

**Files:**
- Create: `deploy/com.mindenhall.ic-tracker.plist.template`, `deploy/install_launchd.sh`, `tests/ic_tracker/test_deploy.py`
- Modify: `README.md`, `example.py`
- Delete: `sso_login.py`, `normalized.py`, `summary.py`, `current_assignments.py`

**Interfaces:**
- Plist placeholders: `@PROJECT_DIR@`, `@HOME@`. Job label `com.mindenhall.ic-tracker`, runs `@PROJECT_DIR@/.venv/bin/ic-tracker run` daily at 07:00 with `WorkingDirectory=@PROJECT_DIR@`, logs to `@HOME@/Library/Logs/ic-tracker.log`.

- [ ] **Step 1: Write failing test**

`tests/ic_tracker/test_deploy.py`:
```python
import plistlib
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[2] / "deploy" / "com.mindenhall.ic-tracker.plist.template"


def test_template_renders_to_a_valid_daily_7am_job():
    text = TEMPLATE.read_text().replace("@PROJECT_DIR@", "/p").replace("@HOME@", "/h")
    plist = plistlib.loads(text.encode())
    assert plist["Label"] == "com.mindenhall.ic-tracker"
    assert plist["ProgramArguments"] == ["/p/.venv/bin/ic-tracker", "run"]
    assert plist["StartCalendarInterval"] == {"Hour": 7, "Minute": 0}
    assert plist["WorkingDirectory"] == "/p"
    assert plist["StandardOutPath"] == "/h/Library/Logs/ic-tracker.log"
    assert "@" not in text
```

- [ ] **Step 2: Run to verify failure** (template missing).

- [ ] **Step 3: Implement**

`deploy/com.mindenhall.ic-tracker.plist.template`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.mindenhall.ic-tracker</string>
    <key>ProgramArguments</key>
    <array>
        <string>@PROJECT_DIR@/.venv/bin/ic-tracker</string>
        <string>run</string>
    </array>
    <key>WorkingDirectory</key><string>@PROJECT_DIR@</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>7</integer>
        <key>Minute</key><integer>0</integer>
    </dict>
    <key>StandardOutPath</key><string>@HOME@/Library/Logs/ic-tracker.log</string>
    <key>StandardErrorPath</key><string>@HOME@/Library/Logs/ic-tracker.log</string>
</dict>
</plist>
```
`deploy/install_launchd.sh` (executable):
```bash
#!/bin/bash
# Install the daily 07:00 launchd job. Run `ic-tracker auth` and `ic-tracker run --dry-run` first.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LABEL=com.mindenhall.ic-tracker
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
sed -e "s|@PROJECT_DIR@|$PROJECT_DIR|g" -e "s|@HOME@|$HOME|g" \
    "$PROJECT_DIR/deploy/$LABEL.plist.template" > "$DEST"
plutil -lint "$DEST"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$DEST"
echo "Installed $LABEL (daily 07:00). Logs: $HOME/Library/Logs/ic-tracker.log"
echo "Uninstall: launchctl bootout gui/$(id -u)/$LABEL && rm $DEST"
```
Update `example.py` to import `from ic_tracker.ic.source import fetch_student_data, ...` and `from ic_tracker.ic.sso import sso_login`, printing `fetch_student_data(client, name, date.today())` results via `NormalizedAssignment.score_display` (no summary import). Delete the four root-level modules. Add a "ic-tracker" section to `README.md` covering: install (`pip install -e ".[tracker]"`), `.env` (see `.env.example`), commands, token renewal (`ic-tracker auth` every 7 days while in Testing; publish the app to stop), going live (change `TRACKER_EMAIL_TO/CC`), scheduling (`deploy/install_launchd.sh`), and running tests.

- [ ] **Step 4: Run to verify pass** — `.venv/bin/python -m pytest -q` (full suite) and `python -c "import example"` equivalent check (`.venv/bin/python -m pyflakes example.py` is not installed; instead run `.venv/bin/python -c "import ast,sys;ast.parse(open('example.py').read())"`).
- [ ] **Step 5: Commit** [commit-gated]

---

### Task 15: Verification

- [ ] **Step 1:** `.venv/bin/python -m pytest -q` — all tests pass, no network access used.
- [ ] **Step 2:** `.venv/bin/ic-tracker run --dry-run --out <scratchpad>/dry-run` against live Infinite Campus (uses `.env`; no Google access). Open `email.html` and `email.txt`; check that: summary counts equal the earlier live numbers (Alex S1 minus Seminar), no Seminar rows, rows sorted by class then due date, excused/absent rows are not highlighted.
- [ ] **Step 3:** Compare the dry-run per-class counts with the old tab `2026-10-11` logic by running `history_from_tab` on the local xlsx values (read-only) as a cross-check of the definition (same classes, counts plausible given four days of change).
- [ ] **Step 4:** Write the morning summary: what is done, what could not be verified without Google (`auth`, `migrate`, `run`), and the exact next commands.

## Self-Review Notes
- **Spec coverage:** goal/run steps (Tasks 4, 5, 8, 12), definitions (3, 4), package structure (all), spreadsheet layout and History (5, 8, 11), email and expiry footer (6), token lifecycle and `ic-tracker auth` (7, 13), error handling (10, 12, 13), scheduling (14), testing and `.gitignore` (1, 15), `--dry-run` (12, 13), recipients in testing (2, 12). Library commits are already in the working tree.
- **Type consistency:** `HistoryRow(run_date, course, assignments, missing, zeros)` is used identically in Tasks 3, 8, 11, 12. `TabData(values, highlight_rows, data_cols, total_cols)` in Tasks 5, 8, 12. Gateway method names `write_tab`, `upsert_history`, `read_history`, `tab_titles`, `read_tab_values` match across Tasks 8, 11, 12.
- **Not verifiable overnight:** Google consent, the real 1Password read (the item uses fields `username` for the client ID and `credential` for the client secret, overridable via `TRACKER_OP_*_REF`), the Drive xlsx conversion, and a real Sheets/Gmail call. These need the user in the morning.
