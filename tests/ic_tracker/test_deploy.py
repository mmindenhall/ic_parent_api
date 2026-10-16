import plistlib
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[2] / "deploy" / "com.mindenhall.ic-tracker.plist.template"


def test_template_renders_to_a_valid_weekday_7am_job():
    text = TEMPLATE.read_text().replace("@PROJECT_DIR@", "/p").replace("@HOME@", "/h")
    plist = plistlib.loads(text.encode())
    assert plist["Label"] == "com.mindenhall.ic-tracker"
    assert plist["ProgramArguments"] == ["/p/.venv/bin/ic-tracker", "run"]
    # launchd weekdays: 1 = Monday ... 5 = Friday; no entry for Saturday (6) or Sunday (0/7)
    assert plist["StartCalendarInterval"] == [{"Weekday": d, "Hour": 7, "Minute": 0} for d in range(1, 6)]
    assert plist["WorkingDirectory"] == "/p"
    assert plist["StandardOutPath"] == "/h/Library/Logs/ic-tracker.log"
    assert "@" not in text
