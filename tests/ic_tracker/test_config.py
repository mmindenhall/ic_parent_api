from pathlib import Path

import pytest

from ic_tracker.config import ConfigError, load_settings

BASE = {
    "IC_BASE_URL": "https://x.infinitecampus.org",
    "IC_USERNAME": "u",
    "IC_PASSWORD": "p",
    "IC_DISTRICT": "d",
    "TRACKER_EMAIL_TO": "a@example.com",
    "TRACKER_STUDENTS": "Alex, Sam",
}


def test_defaults():
    s = load_settings(BASE)
    assert s.email_to == ("a@example.com",)
    assert s.email_cc == () and s.alert_to == ()
    assert s.students == ("Alex", "Sam")
    assert s.student == "Alex"          # the first listed name is the default
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
    for name in ("IC_USERNAME", "IC_PASSWORD", "IC_DISTRICT", "TRACKER_EMAIL_TO", "TRACKER_STUDENTS"):
        assert name in str(err.value)


def test_bad_ttl_is_a_config_error():
    with pytest.raises(ConfigError):
        load_settings({**BASE, "TRACKER_TOKEN_TTL_DAYS": "soon"})


def test_1password_refs_use_username_and_credential_fields():
    s = load_settings(BASE)
    assert s.op_client_id_ref == "op://Private/Google Personal Automation Hub OAuth/username"
    assert s.op_client_secret_ref == "op://Private/Google Personal Automation Hub OAuth/credential"


def test_1password_refs_can_be_overridden():
    env = {**BASE, "TRACKER_OP_CLIENT_ID_REF": "op://V/I/a", "TRACKER_OP_CLIENT_SECRET_REF": "op://V/I/b"}
    s = load_settings(env)
    assert (s.op_client_id_ref, s.op_client_secret_ref) == ("op://V/I/a", "op://V/I/b")


def test_students_list_is_required_and_must_not_be_blank():
    env = {k: v for k, v in BASE.items() if k != "TRACKER_STUDENTS"}
    with pytest.raises(ConfigError):
        load_settings(env)
    with pytest.raises(ConfigError):
        load_settings({**BASE, "TRACKER_STUDENTS": " , "})


def test_drive_folder_follows_the_selected_student():
    from dataclasses import replace
    s = replace(load_settings(BASE), student="Sam")
    assert s.drive_folder == "Kids/Sam"


def test_drive_folder_setting_can_be_a_template_or_a_fixed_path():
    assert load_settings({**BASE, "TRACKER_DRIVE_FOLDER": "Family/{student}/Reports"}).drive_folder == "Family/Alex/Reports"
    assert load_settings({**BASE, "TRACKER_DRIVE_FOLDER": "Shared/Reports"}).drive_folder == "Shared/Reports"
