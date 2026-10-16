import base64
import email
from email.header import decode_header, make_header
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
    assert str(make_header(decode_header(msg["Subject"]))) == "Café check-in"


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
                          "TRACKER_EMAIL_TO": "a@x.com", "TRACKER_STUDENTS": "Alex", "TRACKER_ALERT_TO": alert_to})


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
