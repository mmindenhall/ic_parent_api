"""Failure alerts: macOS notification always, email to TRACKER_ALERT_TO when possible."""
from __future__ import annotations

import logging
import subprocess
from typing import Callable, Optional

from ic_tracker.config import Settings

logger = logging.getLogger(__name__)


def _applescript_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def notify(title: str, message: str, run=subprocess.run) -> None:
    script = f"display notification {_applescript_quote(message)} with title {_applescript_quote(title)}"
    try:
        run(["osascript", "-e", script], check=False, capture_output=True)
    except Exception as error:  # a failed notification must never mask the original error
        logger.warning("Could not show notification: %s", error)


def report_failure(settings: Settings, title: str, message: str, *, notify_fn: Callable = notify,
                   email_fn: Optional[Callable] = None) -> None:
    logger.error("%s: %s", title, message)
    notify_fn(title, message)
    if settings.alert_to and email_fn is not None:
        try:
            email_fn(settings.alert_to, title, message)
        except Exception as error:
            logger.warning("Could not send failure email: %s", error)
