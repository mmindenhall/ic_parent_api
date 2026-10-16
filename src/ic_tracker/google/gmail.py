"""Gmail sending."""
from __future__ import annotations

import base64
from email.message import EmailMessage


def build_raw_message(to, cc, subject: str, text: str, html: str) -> str:
    message = EmailMessage()
    message["To"] = ", ".join(to)
    if cc:
        message["Cc"] = ", ".join(cc)
    message["Subject"] = subject
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    return base64.urlsafe_b64encode(message.as_bytes()).decode()


class GmailGateway:
    def __init__(self, service):
        self._svc = service

    def send(self, to, cc, subject: str, text: str, html: str) -> str:
        raw = build_raw_message(to, cc, subject, text, html)
        sent = self._svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        return sent["id"]
