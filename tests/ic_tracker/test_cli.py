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


def test_parser_knows_all_commands():
    for command in ("auth", "migrate", "status"):
        assert cli.build_parser().parse_args([command]).command == command


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


def _settings():
    from ic_tracker.config import load_settings
    return load_settings({"IC_BASE_URL": "u", "IC_USERNAME": "u", "IC_PASSWORD": "p", "IC_DISTRICT": "d",
                          "TRACKER_EMAIL_TO": "a@x.com", "TRACKER_STUDENTS": "Alex,Sam"})


def test_choose_student_defaults_to_first_listed_name():
    assert cli._choose_student(_settings(), None).student == "Alex"


def test_choose_student_matches_case_insensitively_and_uses_listed_spelling():
    assert cli._choose_student(_settings(), "sAM").student == "Sam"


def test_choose_student_rejects_names_not_in_the_list():
    with pytest.raises(ConfigError) as err:
        cli._choose_student(_settings(), "Pat")
    assert "Alex" in str(err.value) and "Sam" in str(err.value)


def test_run_now_is_the_real_clock_unless_a_date_is_forced():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    settings = _settings()
    assert cli._run_now(None, date(2026, 10, 15), settings) is None
    forced = cli._run_now(date(2026, 10, 15), date(2026, 10, 15), settings)
    assert forced == datetime(2026, 10, 15, 7, 0, tzinfo=ZoneInfo(settings.timezone))


def test_dry_run_help_does_not_claim_no_google_calls():
    text = cli.build_parser().parse_args(["run"]) and cli.build_parser().format_help()
    sub = next(a for a in cli.build_parser()._actions if getattr(a, "choices", None) and "run" in a.choices)
    run_help = sub.choices["run"].format_help()
    assert "no Google calls" not in run_help and "History" in run_help
