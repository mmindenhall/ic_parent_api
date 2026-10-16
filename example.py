"""Example: use the ic_parent_api library to print a child's current-term assignments.

usage: python example.py alex|sam      (first name, case-insensitive)

Reads credentials from a .env file in the project root (see .env.example).
The daily report lives in the `ic-tracker` command; this file only shows library usage.
"""
import argparse
import asyncio
import os
from datetime import date

from dotenv import load_dotenv

from ic_parent_api import InfiniteCampus
from ic_tracker.ic.source import fetch_student_data
from ic_tracker.ic.sso import sso_login

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Missing {name} in .env")
    return value


async def main(first_name: str) -> None:
    base_url, username, password = _require("IC_BASE_URL"), _require("IC_USERNAME"), _require("IC_PASSWORD")
    # Jeffco uses SSO, so sign in with a browser and hand the cookies to the client.
    cookies = await sso_login(base_url, username, password)
    client = InfiniteCampus(base_url, username, password, _require("IC_DISTRICT"), cookies=cookies)

    data = await fetch_student_data(client, first_name, date.today())
    print(f"{data.student_first_name}: term {data.term_name}, {len(data.assignments)} assignments")
    for a in sorted(data.assignments, key=lambda a: (a.course, a.due)):
        print(f"{a.due:%Y-%m-%d}  {a.course[:28]:<28}  {a.name[:60]:<60}  {a.score_display:>9}  {a.status}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("student", help="student first name (case-insensitive)")
    asyncio.run(main(parser.parse_args().student))
