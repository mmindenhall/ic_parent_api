"""Test _cmd_run command."""
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from ic_tracker import cli
from ic_tracker.config import ConfigError, load_settings
from ic_tracker.google.auth import AuthExpiredError


def _settings():
    """Create test settings."""
    return load_settings({
        "IC_BASE_URL": "u",
        "IC_USERNAME": "u",
        "IC_PASSWORD": "p",
        "IC_DISTRICT": "d",
        "TRACKER_EMAIL_TO": "a@x.com",
        "TRACKER_STUDENTS": "Alex,Sam",
        "TRACKER_TIMEZONE": "America/Denver",
    })


def test_cmd_run_sheet_not_found_raises_config_error_with_migrate_hint(monkeypatch):
    """Live run with Sheet not found raises ConfigError mentioning 'ic-tracker migrate'."""
    settings = _settings()
    args = cli.build_parser().parse_args(["run"])

    monkeypatch.setattr("ic_tracker.cli._load_settings", lambda: settings)

    # Mock _services to return services
    drive_svc = MagicMock()
    sheets_svc = MagicMock()
    gmail_svc = MagicMock()
    monkeypatch.setattr(
        "ic_tracker.cli._services",
        lambda s: (drive_svc, sheets_svc, gmail_svc)
    )

    # Mock fetch at source
    monkeypatch.setattr("ic_tracker.ic.source.fetch", AsyncMock(return_value=[]))

    # Mock DriveGateway at source
    drive_gateway_mock = MagicMock()
    drive_gateway_mock.find_file.return_value = None
    drive_gateway_mock.find_folder.return_value = "folder_id"

    def drive_gateway_init(svc):
        return drive_gateway_mock

    monkeypatch.setattr("ic_tracker.google.drive.DriveGateway", drive_gateway_init)

    with pytest.raises(ConfigError) as exc_info:
        cli._cmd_run(args)

    assert "ic-tracker migrate" in str(exc_info.value)


def test_cmd_run_unknown_student_raises_config_error_before_fetch(monkeypatch):
    """--student Pat (not in TRACKER_STUDENTS) raises ConfigError before any fetch happens."""
    settings = _settings()
    args = cli.build_parser().parse_args(["run", "--student", "Pat"])

    monkeypatch.setattr("ic_tracker.cli._load_settings", lambda: settings)

    # Mock fetch to raise an error if called
    fetch_mock = AsyncMock(side_effect=AssertionError("fetch should not be called"))
    monkeypatch.setattr("ic_tracker.ic.source.fetch", fetch_mock)

    with pytest.raises(ConfigError) as exc_info:
        cli._cmd_run(args)

    assert "Pat" in str(exc_info.value)
    # Verify fetch was never called
    fetch_mock.assert_not_called()


def test_cmd_run_student_name_case_insensitive_fetches_correct_name(monkeypatch):
    """--student sam (case-insensitive) fetches for 'Sam'."""
    settings = _settings()
    args = cli.build_parser().parse_args(["run", "--student", "sam"])

    monkeypatch.setattr("ic_tracker.cli._load_settings", lambda: settings)

    # Mock _services
    drive_svc = MagicMock()
    sheets_svc = MagicMock()
    gmail_svc = MagicMock()
    monkeypatch.setattr(
        "ic_tracker.cli._services",
        lambda s: (drive_svc, sheets_svc, gmail_svc)
    )

    # Mock fetch and capture the settings passed to it
    fetch_calls = []
    async def fetch_fn(s, d):
        fetch_calls.append((s, d))
        return []

    monkeypatch.setattr("ic_tracker.ic.source.fetch", fetch_fn)

    # Mock DriveGateway.find_file to return a sheet
    sheet_data = {"id": "sheet_123"}
    drive_gateway_mock = MagicMock()
    drive_gateway_mock.find_file.return_value = sheet_data
    drive_gateway_mock.find_folder.return_value = "folder_id"

    monkeypatch.setattr(
        "ic_tracker.google.drive.DriveGateway",
        lambda svc: drive_gateway_mock
    )

    # Mock other dependencies
    monkeypatch.setattr("ic_tracker.google.sheets.SheetsGateway", lambda svc: MagicMock())
    monkeypatch.setattr("ic_tracker.google.gmail.GmailGateway", lambda svc: MagicMock())
    monkeypatch.setattr(
        "ic_tracker.runner.run_report",
        MagicMock(return_value=MagicMock(tab_title="T", needs_attention=0, recipients=[], tab_url="http"))
    )
    monkeypatch.setattr("ic_tracker.google.auth.load_token_issued_at", MagicMock(return_value=None))
    monkeypatch.setattr("ic_tracker.google.auth.token_days_remaining", MagicMock(return_value=None))

    cli._cmd_run(args)

    # Verify fetch was called with 'Sam' as the student
    assert len(fetch_calls) == 1
    fetched_settings = fetch_calls[0][0]
    assert fetched_settings.student == "Sam"


def test_cmd_run_date_argument_passed_to_run_report(monkeypatch):
    """--date 2026-10-15 is passed as run_date to run_report."""
    settings = _settings()
    args = cli.build_parser().parse_args(["run", "--date", "2026-10-15"])

    monkeypatch.setattr("ic_tracker.cli._load_settings", lambda: settings)

    # Mock _services
    monkeypatch.setattr(
        "ic_tracker.cli._services",
        lambda s: (MagicMock(), MagicMock(), MagicMock())
    )

    # Mock fetch
    monkeypatch.setattr("ic_tracker.ic.source.fetch", AsyncMock(return_value=[]))

    # Mock DriveGateway
    drive_gateway_mock = MagicMock()
    drive_gateway_mock.find_file.return_value = {"id": "sheet_123"}
    drive_gateway_mock.find_folder.return_value = "folder_id"
    monkeypatch.setattr("ic_tracker.google.drive.DriveGateway", lambda svc: drive_gateway_mock)

    # Mock other dependencies and capture run_report call
    run_report_calls = []

    def run_report_fn(**kwargs):
        run_report_calls.append(kwargs)
        return MagicMock(tab_title="T", needs_attention=0, recipients=[], tab_url="http")

    monkeypatch.setattr("ic_tracker.google.sheets.SheetsGateway", lambda svc: MagicMock())
    monkeypatch.setattr("ic_tracker.google.gmail.GmailGateway", lambda svc: MagicMock())
    monkeypatch.setattr("ic_tracker.runner.run_report", run_report_fn)
    monkeypatch.setattr("ic_tracker.google.auth.load_token_issued_at", MagicMock(return_value=None))
    monkeypatch.setattr("ic_tracker.google.auth.token_days_remaining", MagicMock(return_value=None))

    cli._cmd_run(args)

    # Verify run_date was passed correctly
    assert len(run_report_calls) == 1
    assert run_report_calls[0]["run_date"] == date(2026, 10, 15)


def test_cmd_run_default_date_is_today_in_settings_timezone(monkeypatch):
    """Without --date, the run_date is today in the settings timezone."""
    settings = _settings()
    args = cli.build_parser().parse_args(["run"])

    monkeypatch.setattr("ic_tracker.cli._load_settings", lambda: settings)

    # Mock _services
    monkeypatch.setattr(
        "ic_tracker.cli._services",
        lambda s: (MagicMock(), MagicMock(), MagicMock())
    )

    # Mock fetch
    monkeypatch.setattr("ic_tracker.ic.source.fetch", AsyncMock(return_value=[]))

    # Mock DriveGateway
    drive_gateway_mock = MagicMock()
    drive_gateway_mock.find_file.return_value = {"id": "sheet_123"}
    drive_gateway_mock.find_folder.return_value = "folder_id"
    monkeypatch.setattr("ic_tracker.google.drive.DriveGateway", lambda svc: drive_gateway_mock)

    # Mock other dependencies and capture run_report call
    run_report_calls = []

    def run_report_fn(**kwargs):
        run_report_calls.append(kwargs)
        return MagicMock(tab_title="T", needs_attention=0, recipients=[], tab_url="http")

    monkeypatch.setattr("ic_tracker.google.sheets.SheetsGateway", lambda svc: MagicMock())
    monkeypatch.setattr("ic_tracker.google.gmail.GmailGateway", lambda svc: MagicMock())
    monkeypatch.setattr("ic_tracker.runner.run_report", run_report_fn)
    monkeypatch.setattr("ic_tracker.google.auth.load_token_issued_at", MagicMock(return_value=None))
    monkeypatch.setattr("ic_tracker.google.auth.token_days_remaining", MagicMock(return_value=None))

    cli._cmd_run(args)

    # Verify run_date is today in the settings timezone
    assert len(run_report_calls) == 1
    expected_date = datetime.now(ZoneInfo(settings.timezone)).date()
    assert run_report_calls[0]["run_date"] == expected_date


def test_cmd_run_services_auth_expired_error_fails_fast_before_fetch(monkeypatch):
    """If _services raises AuthExpiredError, fetch is never called."""
    settings = _settings()
    args = cli.build_parser().parse_args(["run"])

    monkeypatch.setattr("ic_tracker.cli._load_settings", lambda: settings)

    # Mock _services to raise AuthExpiredError
    monkeypatch.setattr(
        "ic_tracker.cli._services",
        lambda s: (_ for _ in ()).throw(AuthExpiredError("token expired"))
    )

    # Mock fetch to raise if called
    fetch_mock = AsyncMock(side_effect=AssertionError("fetch should not be called"))
    monkeypatch.setattr("ic_tracker.ic.source.fetch", fetch_mock)

    with pytest.raises(AuthExpiredError):
        cli._cmd_run(args)

    # Verify fetch was never called
    fetch_mock.assert_not_called()


def test_cmd_run_dry_run_calls_write_dry_run_not_run_report(monkeypatch):
    """--dry-run calls write_dry_run and does not call run_report."""
    settings = _settings()
    args = cli.build_parser().parse_args(["run", "--dry-run"])

    monkeypatch.setattr("ic_tracker.cli._load_settings", lambda: settings)

    # Mock fetch
    monkeypatch.setattr("ic_tracker.ic.source.fetch", AsyncMock(return_value=[]))

    # Mock write_dry_run
    write_dry_run_calls = []

    def write_dry_run_fn(**kwargs):
        write_dry_run_calls.append(kwargs)
        return []

    monkeypatch.setattr("ic_tracker.runner.write_dry_run", write_dry_run_fn)

    # Mock run_report to raise if called
    run_report_mock = MagicMock(side_effect=AssertionError("run_report should not be called"))
    monkeypatch.setattr("ic_tracker.runner.run_report", run_report_mock)

    # Mock _read_history_if_possible
    monkeypatch.setattr("ic_tracker.cli._read_history_if_possible", lambda s: [])

    result = cli._cmd_run(args)

    # Verify write_dry_run was called
    assert len(write_dry_run_calls) == 1
    assert write_dry_run_calls[0]["data"] == []
    # Verify run_report was not called
    run_report_mock.assert_not_called()
    # Verify return code is 0
    assert result == 0


def test_cmd_run_dry_run_history_failure_returns_zero_with_empty_history(monkeypatch):
    """Dry run: if reading History fails, still returns 0 with history=[]."""
    settings = _settings()
    args = cli.build_parser().parse_args(["run", "--dry-run"])

    monkeypatch.setattr("ic_tracker.cli._load_settings", lambda: settings)

    # Mock fetch
    monkeypatch.setattr("ic_tracker.ic.source.fetch", AsyncMock(return_value=[]))

    # Mock write_dry_run and capture calls
    write_dry_run_calls = []

    def write_dry_run_fn(**kwargs):
        write_dry_run_calls.append(kwargs)
        return []

    monkeypatch.setattr("ic_tracker.runner.write_dry_run", write_dry_run_fn)

    # Mock _read_history_if_possible to simulate failure by returning []
    # (the function itself handles exceptions and returns [])
    monkeypatch.setattr("ic_tracker.cli._read_history_if_possible", lambda s: [])

    result = cli._cmd_run(args)

    # Verify write_dry_run was called with empty history
    assert len(write_dry_run_calls) == 1
    assert write_dry_run_calls[0]["history"] == []
    # Verify return code is 0
    assert result == 0
