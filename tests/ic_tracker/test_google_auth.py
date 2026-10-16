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
                          "TRACKER_EMAIL_TO": "a@x.com", "TRACKER_STUDENTS": "Alex", "TRACKER_CACHE_DIR": str(tmp_path)})


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
    """Stands in for `op read <ref>`; answers by the 1Password reference it is asked for."""

    def __init__(self):
        self.calls = []

    def __call__(self, args, **kw):
        self.calls.append(args[-1])
        return NS(stdout="id-from-op\n" if args[-1].endswith("/username") else "secret-from-op\n")


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
