"""Sign in to a district that uses SSO (e.g. Jeffco) with Playwright and return session cookies.

Pass the result to InfiniteCampus(..., cookies=cookies).
"""
from __future__ import annotations

from urllib.parse import urlparse

from playwright.async_api import async_playwright

JEFFCO_START_URL = (
    "https://www.jeffcopublicschools.org/services/technology/"
    "digital-learning-applications/infinite-campus"
)


async def sso_login(base_url: str, username: str, password: str,
                    headless: bool = True, timeout: int = 30000) -> dict:
    """Return {cookie_name: value} for the Infinite Campus host after SSO login."""
    host = urlparse(base_url).hostname
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        try:
            page = await browser.new_page()
            await page.goto(JEFFCO_START_URL, wait_until="domcontentloaded")
            await page.get_by_role("link", name="Families: Log Into Infinite Campus").click()
            await page.get_by_placeholder("Username").fill(username)
            await page.get_by_placeholder("Password").fill(password)
            await page.get_by_role("button", name="Sign in").click()
            try:
                await page.wait_for_url("**/campus/**", timeout=timeout)
            except Exception as error:
                if await page.get_by_placeholder("Password").count():
                    raise RuntimeError("SSO login form still showing: bad credentials?") from error
                raise
            # Let the portal finish setting its session cookies.
            await page.wait_for_load_state("networkidle")
            cookies = await page.context.cookies()
        finally:
            await browser.close()
    return {c["name"]: c["value"] for c in cookies if host and host in c["domain"]}
