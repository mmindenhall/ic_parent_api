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
    """Whole days left before a Testing-status refresh token expires; None when no TTL is configured."""
    if ttl_days is None:
        return None
    return ttl_days - (now - issued_at).days


def write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.parent / f"{path.name}.tmp"
    temp_path.unlink(missing_ok=True)   # a stale file from an earlier crash would block O_EXCL
    try:
        fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
            handle.flush()
        os.replace(temp_path, path)
    except Exception:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise


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
    if not data or "issued_at" not in data:
        return None
    try:
        return datetime.fromisoformat(data["issued_at"])
    except (ValueError, TypeError):
        return None


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
    token_path = _token_path(settings)

    # Check if file exists to distinguish missing from unreadable
    file_exists = token_path.exists()
    stored = _read_json(token_path)

    if not file_exists:
        raise AuthExpiredError("No Google token is cached. Run: ic-tracker auth")

    if not stored or "authorized_user" not in stored:
        raise AuthExpiredError(
            "The cached Google token is unreadable (invalid JSON or missing fields). Run: ic-tracker auth")

    if credentials_factory is None:
        from google.oauth2.credentials import Credentials

        def credentials_factory(info):
            return Credentials.from_authorized_user_info(info, SCOPES)
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
    """Return (drive, sheets, gmail) API service objects."""
    from googleapiclient.discovery import build
    return (build("drive", "v3", credentials=creds, cache_discovery=False),
            build("sheets", "v4", credentials=creds, cache_discovery=False),
            build("gmail", "v1", credentials=creds, cache_discovery=False))
