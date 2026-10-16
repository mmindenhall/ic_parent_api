# Infinite Campus Parent API

This is an async wrapper for the [Infinite Campus API](https://canvas.instructure.com/doc/api/).  There are a few types of objects this will retrieve based on the assumption that you are a parent with students enrolled with Canvas.  

The types of objects that can be returned include:

- Students
- Courses
- Assignments
- Terms

This module is provided for use with the Home Assistant custom integration [Infinite Campus](https://github.com/schwartzpub/infinite_campus_hassio) however it could be useful as a standalone module for your own projects as well.

## Installing

To install the module use:

```shell
python3 -m pip install ic-parent-api
```

### Usage

At the login page inspect the page with developer tools and search for the hidden input with the name `appName`. Like in the image below.

![Screenshot 2022-09-16 171957](https://user-images.githubusercontent.com/13734613/190816004-a062b221-0653-4655-9b37-b67211350e6b.jpg)

Example usage to get students, printing first names:

```python
import asyncio
from ic_parent_api import InfiniteCampus

base_url = "https://school.infinitecampus.com"
username = "myusername"
password = "myp4ssw0rd!"
district = "schooldistrict" #known as appName to infinitecampus

async def get_students():
    client = InfiniteCampus(f"{base_url}",f"{username}",f"{password}",f"{district}")
    return await client.students()

students = asyncio.run(get_students())

for student in students:
    print(student.firstname)
```

## ic-tracker: daily assignment report

`ic-tracker` (in `src/ic_tracker`) uses this library to build a daily report for a parent: it fetches a student's
current-term assignments, writes a dated tab plus a `History` tab to a Google Sheet, and emails a trend grid of
missing and zero-scored work (plus each class's current term grade in a final "Today's Grades" column) with teacher comments (and upcoming commented assignments), and a link to the new tab. It is separate from the library and has its own
optional dependencies.

### Setup

```shell
python3 -m venv .venv && .venv/bin/pip install -e ".[tracker]"
.venv/bin/playwright install chromium-headless-shell
cp .env.example .env        # then fill in the Infinite Campus login and recipients
```

Districts that use SSO (such as Jeffco) cannot log in through the library's `verify.jsp` call. `ic-tracker` signs in
with Playwright and passes the session cookies to the library (`InfiniteCampus(..., cookies=...)`).

### Commands

| Command | What it does |
|---|---|
| `ic-tracker auth` | One-time Google consent. Caches the token in `~/.cache/ic-tracker/` (mode 600). Re-run it to renew. |
| `ic-tracker migrate` | Converts `Assignments Tracker.xlsx` in the Drive folder to a Google Sheet and backfills `History`. |
| `ic-tracker run --dry-run` | Fetches real data and writes `email.html`, `email.txt`, `tab.tsv`. No Google calls, no email. |
| `ic-tracker run` | Writes the dated tab and `History`, then sends the email. Safe to rerun on the same day. |
| `ic-tracker status` | Shows the Google token age and days remaining. |

### Google token lifetime

While the Google OAuth consent screen is in **Testing** status, refresh tokens expire 7 days after they are issued.
The email footer shows the days remaining; run `ic-tracker auth` to renew. After the app is published to Production
(Cloud Console, OAuth consent screen, Publish app), run `ic-tracker auth` once more and set
`TRACKER_TOKEN_TTL_DAYS=none` to remove the reminder.

### Going live and scheduling

`TRACKER_STUDENTS` lists the students' first names (required). The first is the default for `ic-tracker run`;
`--student NAME` picks another listed name. The Drive folder defaults to `Kids/<first name>`.

While testing, `TRACKER_EMAIL_TO` is the parent only. To go live, set `TRACKER_EMAIL_TO` to the student and
`TRACKER_EMAIL_CC` to the parents. The tool never changes Drive sharing; share the Sheet in Drive yourself.
To run on weekdays (Mon-Fri) at 07:00 (macOS): `deploy/install_launchd.sh`.

### Tests

```shell
.venv/bin/python -m pytest
```
