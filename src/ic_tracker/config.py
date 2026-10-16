"""Settings loaded from environment variables (usually a .env file)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional

_REQUIRED = ("IC_BASE_URL", "IC_USERNAME", "IC_PASSWORD", "IC_DISTRICT", "TRACKER_EMAIL_TO", "TRACKER_STUDENTS")
_OP_ITEM = "op://Private/Google Personal Automation Hub OAuth"

# Module-level defaults used by load_settings and field defaults
_DEFAULT_TIMEZONE = "America/Denver"
_DEFAULT_EXCLUDE_COURSES = ("Seminar",)
_DEFAULT_TOKEN_TTL_DAYS = 7
_DEFAULT_SHEET_NAME = "Assignments Tracker"
_DEFAULT_DRIVE_FOLDER_TEMPLATE = "Kids/{student}"
_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "ic-tracker"
_DEFAULT_OP_CLIENT_ID_REF = f"{_OP_ITEM}/username"
_DEFAULT_OP_CLIENT_SECRET_REF = f"{_OP_ITEM}/credential"


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
    ic_password: str = field(repr=False)
    ic_district: str
    email_to: tuple[str, ...]
    students: tuple[str, ...]               # first names from TRACKER_STUDENTS; the first is the default
    student: str                            # the student this run reports on (the first listed name unless overridden)
    email_cc: tuple[str, ...] = ()
    alert_to: tuple[str, ...] = ()
    timezone: str = _DEFAULT_TIMEZONE
    exclude_courses: tuple[str, ...] = _DEFAULT_EXCLUDE_COURSES
    token_ttl_days: Optional[int] = _DEFAULT_TOKEN_TTL_DAYS
    sheet_name: str = _DEFAULT_SHEET_NAME
    drive_folder_template: str = _DEFAULT_DRIVE_FOLDER_TEMPLATE   # '{student}' is replaced with the selected first name
    cache_dir: Path = _DEFAULT_CACHE_DIR
    op_client_id_ref: str = _DEFAULT_OP_CLIENT_ID_REF             # the OAuth client ID is stored in the item's username field
    op_client_secret_ref: str = _DEFAULT_OP_CLIENT_SECRET_REF     # and the client secret in its credential field

    def __post_init__(self) -> None:
        if not self.students:
            raise ConfigError("students must not be empty")
        if self.student not in self.students:
            raise ConfigError(f"student={self.student!r} must be one of {self.students!r}")

    @property
    def drive_folder(self) -> str:
        return self.drive_folder_template.replace("{student}", self.student)


def _students(raw: str) -> tuple[str, ...]:
    names = _split(raw)
    if not names:
        raise ConfigError("TRACKER_STUDENTS must list at least one first name, e.g. TRACKER_STUDENTS=Alex,Sam")
    return names


def load_settings(env: Mapping[str, str]) -> Settings:
    missing = [name for name in _REQUIRED if not env.get(name)]
    if missing:
        raise ConfigError("Missing required settings: " + ", ".join(missing))
    students = _students(env["TRACKER_STUDENTS"])
    return Settings(
        ic_base_url=env["IC_BASE_URL"],
        ic_username=env["IC_USERNAME"],
        ic_password=env["IC_PASSWORD"],
        ic_district=env["IC_DISTRICT"],
        email_to=_split(env["TRACKER_EMAIL_TO"]),
        students=students,
        student=students[0],
        email_cc=_split(env.get("TRACKER_EMAIL_CC", "")),
        alert_to=_split(env.get("TRACKER_ALERT_TO", "")),
        timezone=env.get("TRACKER_TIMEZONE", _DEFAULT_TIMEZONE),
        exclude_courses=_split(env["TRACKER_EXCLUDE_COURSES"]) if "TRACKER_EXCLUDE_COURSES" in env
        else _DEFAULT_EXCLUDE_COURSES,
        token_ttl_days=_ttl(env["TRACKER_TOKEN_TTL_DAYS"]) if "TRACKER_TOKEN_TTL_DAYS" in env
        else _DEFAULT_TOKEN_TTL_DAYS,
        sheet_name=env.get("TRACKER_SHEET_NAME", _DEFAULT_SHEET_NAME),
        drive_folder_template=env.get("TRACKER_DRIVE_FOLDER", _DEFAULT_DRIVE_FOLDER_TEMPLATE),
        cache_dir=Path(env["TRACKER_CACHE_DIR"]).expanduser() if "TRACKER_CACHE_DIR" in env
        else _DEFAULT_CACHE_DIR,
        op_client_id_ref=env.get("TRACKER_OP_CLIENT_ID_REF", _DEFAULT_OP_CLIENT_ID_REF),
        op_client_secret_ref=env.get("TRACKER_OP_CLIENT_SECRET_REF", _DEFAULT_OP_CLIENT_SECRET_REF),
    )
