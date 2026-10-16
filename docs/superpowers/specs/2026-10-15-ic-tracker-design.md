# ic-tracker: daily Alex assignment report

Date: 2026-10-15
Status: draft for review

## Goal
On weekday mornings (Mon-Fri 07:00 Mountain time), Alex and both parents can see how Alex's missing and zero-scored work is changing, without anyone having to ask for it.

Each run:
1. Fetches Alex's current-term assignments from Infinite Campus (Jeffco SSO).
2. Skips Seminar, sorts by class then due date ascending.
3. Writes them to a dated tab (`YYYY-MM-DD`) in a Google Sheet in Drive folder `Kids/Alex`. If the tab exists, it is cleared and rewritten.
4. Records per-class counts in a `History` tab.
5. Emails a trend grid (today plus the previous 7 runs), today's problem items, and a link to today's tab.

## Decisions made
| Topic | Decision |
|---|---|
| Trigger | `launchd` on this Mac, weekdays (Mon-Fri) at **07:00 America/Denver**; also runnable by hand |
| Google access | Official libraries (`google-api-python-client`, `google-auth-oauthlib`), OAuth client from 1Password item `Google Personal Automation Hub OAuth`; scopes `drive`, `spreadsheets`, `gmail.send` |
| Client credential type | Client ID and secret only; refresh token obtained by `ic-tracker auth` |
| Consent screen | External, **Testing** status for now: refresh token expires 7 days after it is issued |
| Spreadsheet | Existing `Assignments Tracker.xlsx` converted once to a native Google Sheet; the xlsx stays as a backup |
| Trend history | `History` tab (one row per class per run date), backfilled from the converted tabs |
| Sharing | Done manually by Mark in Drive; the tool never changes permissions |
| Code layout | New package `src/ic_tracker` in this repo; library fixes kept as separate commits for an upstream pull request |
| Testing phase email | From Mark to Mark only (`TRACKER_EMAIL_TO=parent1@example.com`, `TRACKER_EMAIL_CC` empty). Going live: `TO=student@example.com`, `CC=parent2@example.com,parent1@example.com` |

## Definitions
- **Problem assignment**: flagged missing, or graded with a score of 0 and not flagged missing. Excused (`e`) and absent (`Ab`) scores are not problems.
- **Needs attention** = missing + zeros, never double-counted.
- **Current term**: the term that started most recently on or before today, across the schedule structures present in the student's assignments.
- **Run**: one execution that completed the Sheet write. Trend columns are runs, not calendar days.
- **Excluded courses**: course names starting with `Seminar` (`TRACKER_EXCLUDE_COURSES`, comma-separated prefixes).

## Package structure (`src/ic_tracker`)
| Module | Job | Depends on |
|---|---|---|
| `config.py` | Settings from `.env` (IC login, recipients, timezone, exclusions, token TTL) | python-dotenv |
| `ic/sso.py` | Playwright login through Jeffco SSO, returns cookies | Playwright |
| `ic/source.py` | Fetch a student's current-term assignments | `ic_parent_api` |
| `model.py` | `NormalizedAssignment` | none |
| `analysis.py` | Course filter, problem classification, per-class summaries, trend math | `model` |
| `google/auth.py` | OAuth consent, token cache, API client construction, token-age calculation | Google libraries |
| `google/drive.py` | Find folder, convert xlsx once | `auth` |
| `google/sheets.py` | Create or clear a dated tab and write it; upsert History rows; tab URL | `auth` |
| `google/gmail.py` | Send a MIME message | `auth` |
| `report/sheet.py` | Rows and formatting for a dated tab (pure) | `analysis` |
| `report/email.py` | HTML and plain-text bodies (pure) | `analysis` |
| `alert.py` | Failure notification (macOS notification and log; email best effort) | Gmail optional |
| `cli.py` | Commands `run`, `auth`, `migrate`, `--dry-run` | all |

`report/*` and `analysis` are pure (data in, data out) and are tested without network access.

## Run flow
1. Load config. Log in via SSO. Fetch assignments for the student whose first name matches (case-insensitive).
2. Abort if zero assignments (never overwrite a tab with empty data).
3. Normalize, exclude courses, classify, summarize.
4. Write the dated tab (insert at the front; if the tab exists, clear it first and rewrite).
5. Upsert History rows for the run date (delete that date's rows, append new ones).
6. Read the last 8 distinct dates from History.
7. Render and send the email.

## Spreadsheet
- Sheet name `Assignments Tracker`, located by name inside `Kids/Alex`.
- Dated tab columns A-K: Class, Due Date, Assignment, Score (raw), Earned, Possible, Percent, Missing, Zero, Status, Comment. Rows that are missing or zero are filled red. Stats block in M-Q: per class Assignments, Missing, Zeros, Needs attention, plus Total.
- `History` columns: Date, Class, Assignments, Missing, Zeros, Needs attention. Totals are computed when read, not stored.
- `migrate` converts the xlsx, then backfills History by recomputing from each old tab's Class, Missing and Zero columns.
- Email link: `https://docs.google.com/spreadsheets/d/<sheetId>/edit#gid=<tabId>`.

## Email
- Subject: `Alex: assignment check-in, Thu Oct 15` (neutral, no counts).
- Summary line leads with change: today's needs-attention total, the previous run, and one week earlier.
- Trend grid: rows = classes, columns = the previous 7 runs plus today, cells = needs-attention counts, bottom row = totals. Today's column is outlined. Soft single-hue shading, no red. Fewer than 8 runs shows what exists.
- Today's items grouped by class, oldest due date first; problem items are tagged Missing or Zero, and upcoming commented items are tagged "Due in the future: <date>".
- Button linking to today's tab.
- **Amended 2026-10-15 (students):** student names are not in the code. `TRACKER_STUDENTS` (required, comma-separated first names) lists them; the first is the default and `run --student NAME` must pick a listed name. The Drive folder defaults to `Kids/{student}` (`TRACKER_DRIVE_FOLDER` overrides; `{student}` is substituted).
- **Amended 2026-10-15 (comments):** each listed item shows the teacher's comment when present. Not-yet-due items that have a comment are also listed under their class, tagged "Due in the future: <date>". They are excluded from the tally, trend grid and History, and appear on quiet days too.
- **Amended 2026-10-15:** the grid ends with a "Today's Grades" column showing each class's in-progress Term Final grade as `D (61.75%)` (from the portal's `progressScore`/`progressPercent`, else the posted score). Grades are email-only; they are not written to the Sheet. If grades cannot be fetched the column is omitted. Otherwise: no generated commentary, praise or warnings (teacher comments are shown as written).
- HTML and plain-text parts, inline styles, table layout, tested to render in Gmail light and dark mode.
- **Sign-in expiry footer** (while `TRACKER_TOKEN_TTL_DAYS` is set): "Google sign-in expires in N days. Renew with `ic-tracker auth`." Emphasized (bold, dark amber) when 2 days or fewer remain. When the value is `none` (after the app moves to Production) the footer is omitted.

## Google token lifecycle (Testing status)
- `ic-tracker auth` opens the browser for consent, stores the refresh token in `~/.cache/ic-tracker/google_token.json` (mode 600) together with `issued_at`, and prints the expiry date and the configured TTL. This is the "easy script" to renew; it can be run from the Claude prompt as `! ic-tracker auth`.
- Days remaining = `TRACKER_TOKEN_TTL_DAYS` (default 7) minus whole days since `issued_at`. Google does not report the expiry, so this is calculated from when the tracker recorded issuing it.
- If a run hits `invalid_grant`, no Sheet write or email happens. A macOS notification and a log line say "run `ic-tracker auth`". (The alert email is attempted when `TRACKER_ALERT_TO` is set, but is expected to fail when the Google token is the cause.)
- Client ID and secret: read from 1Password item `Google Personal Automation Hub OAuth`, cached at `~/.cache/ic-tracker/google_client.json` (mode 600). 1Password is read again only after an auth failure on the cached client, and the cache is rewritten only if the new credentials work.
- Moving the consent screen to Production later is a one-time step in Google Cloud Console (OAuth consent screen, Publish app), followed by `ic-tracker auth` once and setting `TRACKER_TOKEN_TTL_DAYS=none`.

## Error handling
| Failure | Behavior |
|---|---|
| IC login or fetch fails | Nothing written, nothing sent to Alex; macOS notification, log, non-zero exit; email to `TRACKER_ALERT_TO` best effort |
| Zero assignments returned | Abort before any write |
| Google token expired or revoked | As above, with the `ic-tracker auth` instruction |
| Sheet write fails | No email |
| Email fails after Sheet write | Tab and History kept; non-zero exit; rerun is safe (all writes replace) |

## Scheduling
A launchd job template in `deploy/` (`StartCalendarInterval` Mon-Fri 07:00) runs the installed `ic-tracker run` (with no argument, using the first student in `TRACKER_STUDENTS`) and logs to `~/Library/Logs/ic-tracker.log`. A missed run (Mac asleep at 07:00) runs when the Mac wakes. The job needs only `.env` and the `~/.cache` token files; it never prompts for 1Password.

## Testing
- Unit tests (pytest) for `analysis`, `report/sheet`, `report/email`, config parsing and token-age math, using fake data.
- Google modules tested against fake service objects.
- `--dry-run`: fetches real data, renders the email and tab rows into the scratchpad. It writes nothing to Google and sends no email; if the cached Google token works, it reads the History tab (read-only) so the trend grid matches the real email; on any failure it prints a note and the grid shows today only. The footer shows the configured token TTL, not actual remaining days.
- Live smoke test: converted Sheet, email to Mark only, with the xlsx as backup.
- `.gitignore` stops ignoring `tests/`.

## Repository changes
- Library commits (upstreamable, kept separate from tracker work): `cookies` argument on the client; `structure_id` on terms; `str()` in `InfiniteCampusError`; optional `ScheduleDayResponse.duration`; `scoreModifiedDate` field; SSO detection in `authenticate`. Also fetches grades (`class_grades`), holding `ClassGrade` objects in the model, and exposes `InfiniteCampus.grades()` and `get_grades()`.
- Tracker: `src/ic_tracker/`, `deploy/`, `tests/`, `pyproject.toml` extra `tracker` and console script `ic-tracker`. Also: `ic/source.py` fetches grades and `model.py` holds `ClassGrade`; `cli.py` lists the `status` field.
- Root-level scratch modules (`sso_login.py`, `normalized.py`, `summary.py`, `current_assignments.py`) move into the package; `example.py` stays as a library usage example.
- Tracker code uses `from __future__ import annotations` so it imports on the library's declared Python 3.9 floor.
- Later: fork upstream and push; open a pull request with the library commits only.

## Out of scope for now
- Resolved-since-last-run list (needs per-item history).
- Scheduling more than one student (the launchd job reports only the default student, the first listed in `TRACKER_STUDENTS`).
- Automatic sharing of the Sheet.
- Cloud scheduling.
