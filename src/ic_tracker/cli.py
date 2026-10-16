"""Command line interface: run, auth, migrate, status."""
from __future__ import annotations

import argparse
import asyncio
import html
import logging
import os
import sys
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
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
    run.add_argument("--student", help="first name from TRACKER_STUDENTS (default: the first one listed)")
    run.add_argument("--dry-run", action="store_true", help="render files only; no Google calls, no email")
    run.add_argument("--out", type=Path, help="dry-run output directory")
    run.add_argument("--date", type=_date, help="override the run date (YYYY-MM-DD)")
    sub.add_parser("auth", help="one-time Google consent; renews the cached token")
    sub.add_parser("migrate", help="convert the old xlsx to a Google Sheet and backfill History")
    sub.add_parser("status", help="show Google token age and days remaining")
    return parser


def _load_settings() -> Settings:
    from dotenv import find_dotenv, load_dotenv
    load_dotenv(find_dotenv(usecwd=True))
    return load_settings(os.environ)


def _choose_student(settings: Settings, requested: Optional[str]) -> Settings:
    """Select the student for this run; only names listed in TRACKER_STUDENTS are accepted."""
    if not requested:
        return settings
    by_name = {name.casefold(): name for name in settings.students}
    chosen = by_name.get(requested.strip().casefold())
    if chosen is None:
        raise ConfigError(f"'{requested}' is not in TRACKER_STUDENTS. Listed: {', '.join(settings.students)}")
    return replace(settings, student=chosen)


def _services(settings: Settings):
    from ic_tracker.google.auth import build_services, get_credentials
    return build_services(get_credentials(settings))


def _read_history_if_possible(settings: Settings) -> list:
    """Earlier runs for a dry run's grid. Read-only; any failure means the grid shows today only."""
    from ic_tracker.google.drive import SHEET_MIME, DriveGateway
    from ic_tracker.google.sheets import SheetsGateway
    try:
        drive_svc, sheets_svc, _ = _services(settings)
        drive = DriveGateway(drive_svc)
        sheet = drive.find_file(settings.sheet_name, drive.find_folder(settings.drive_folder), SHEET_MIME)
        return SheetsGateway(sheets_svc).read_history(sheet["id"]) if sheet else []
    except Exception as exc:
        print(f"Dry run: could not read History ({exc}); grid shows today only.")
        return []


def _cmd_run(args) -> int:
    from ic_tracker.google.auth import load_token_issued_at, token_days_remaining
    from ic_tracker.google.drive import SHEET_MIME, DriveGateway
    from ic_tracker.google.gmail import GmailGateway
    from ic_tracker.google.sheets import SheetsGateway
    from ic_tracker.ic.source import fetch
    from ic_tracker.runner import run_report, write_dry_run

    settings = _load_settings()
    settings = _choose_student(settings, args.student)
    run_date = args.date or datetime.now(ZoneInfo(settings.timezone)).date()
    if args.dry_run:
        data = asyncio.run(fetch(settings, run_date))
        out = args.out or settings.cache_dir / "dry-run"
        history = _read_history_if_possible(settings)
        for path in write_dry_run(settings=settings, data=data, run_date=run_date, out_dir=out, history=history):
            print(path)
        return 0
    drive_svc, sheets_svc, gmail_svc = _services(settings)   # fail fast on a missing or expired Google token
    data = asyncio.run(fetch(settings, run_date))
    drive = DriveGateway(drive_svc)
    sheet = drive.find_file(settings.sheet_name, drive.find_folder(settings.drive_folder), SHEET_MIME)
    if sheet is None:
        raise ConfigError(
            f"Google Sheet '{settings.sheet_name}' not found in {settings.drive_folder}. Run: ic-tracker migrate")
    issued = load_token_issued_at(settings)
    days = token_days_remaining(issued, datetime.now(timezone.utc), settings.token_ttl_days) if issued else None
    result = run_report(settings=settings, data=data, run_date=run_date, spreadsheet_id=sheet["id"],
                        sheets=SheetsGateway(sheets_svc), gmail=GmailGateway(gmail_svc), token_days_remaining=days)
    print(f"Wrote tab {result.tab_title} ({result.needs_attention} need attention); "
          f"emailed {', '.join(result.recipients)}")
    print(result.tab_url)
    return 0


def _cmd_auth(args) -> int:
    from ic_tracker.google.auth import authorize
    settings = _load_settings()
    issued = authorize(settings)
    if settings.token_ttl_days is None:
        print("Google token cached.")
    else:
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
    """macOS notification always; email TRACKER_ALERT_TO when configured and Gmail still works."""
    from ic_tracker.alert import notify, report_failure
    try:
        settings = _load_settings()
    except ConfigError:
        notify(title, message)
        return

    def email_fn(to, subject, body):
        from ic_tracker.google.gmail import GmailGateway
        _, _, gmail_svc = _services(settings)
        GmailGateway(gmail_svc).send(to, (), subject, body, f"<pre>{html.escape(body)}</pre>")

    report_failure(settings, title, message, notify_fn=notify, email_fn=email_fn)


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
