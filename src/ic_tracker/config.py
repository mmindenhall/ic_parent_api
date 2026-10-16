"""Settings loaded from environment variables (usually a .env file)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

_REQUIRED = ("IC_BASE_URL", "IC_USERNAME", "IC_PASSWORD", "IC_DISTRICT", "TRACKER_EMAIL_TO", "TRACKER_STUDENTS")
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
    students: tuple[str, ...] = ("",)   # first names from TRACKER_STUDENTS; the first is the default
    student: str = ""                   # the student this run reports on (the first listed name unless overridden)
    timezone: str = "America/Denver"
    exclude_courses: tuple[str, ...] = ("Seminar",)
    token_ttl_days: Optional[int] = 7
    sheet_name: str = "Assignments Tracker"
    drive_folder_template: str = "Kids/{student}"   # '{student}' is replaced with the selected first name
    cache_dir: Path = Path.home() / ".cache" / "ic-tracker"
    op_client_id_ref: str = f"{_OP_ITEM}/username"   # the OAuth client ID is stored in the item's username field
    op_client_secret_ref: str = f"{_OP_ITEM}/credential"   # and the client secret in its credential field

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
    defaults = Settings("", "", "", "", ())
    students = _students(env["TRACKER_STUDENTS"])
    return Settings(
        ic_base_url=env["IC_BASE_URL"],
        ic_username=env["IC_USERNAME"],
        ic_password=env["IC_PASSWORD"],
        ic_district=env["IC_DISTRICT"],
        email_to=_split(env["TRACKER_EMAIL_TO"]),
        email_cc=_split(env.get("TRACKER_EMAIL_CC", "")),
        alert_to=_split(env.get("TRACKER_ALERT_TO", "")),
        students=students,
        student=students[0],
        timezone=env.get("TRACKER_TIMEZONE", defaults.timezone),
        exclude_courses=_split(env["TRACKER_EXCLUDE_COURSES"]) if "TRACKER_EXCLUDE_COURSES" in env
        else defaults.exclude_courses,
        token_ttl_days=_ttl(env["TRACKER_TOKEN_TTL_DAYS"]) if "TRACKER_TOKEN_TTL_DAYS" in env
        else defaults.token_ttl_days,
        sheet_name=env.get("TRACKER_SHEET_NAME", defaults.sheet_name),
        drive_folder_template=env.get("TRACKER_DRIVE_FOLDER", defaults.drive_folder_template),
        cache_dir=Path(env["TRACKER_CACHE_DIR"]).expanduser() if "TRACKER_CACHE_DIR" in env
        else defaults.cache_dir,
        op_client_id_ref=env.get("TRACKER_OP_CLIENT_ID_REF", defaults.op_client_id_ref),
        op_client_secret_ref=env.get("TRACKER_OP_CLIENT_SECRET_REF", defaults.op_client_secret_ref),
    )
