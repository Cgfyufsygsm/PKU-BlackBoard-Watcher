from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoginCheckResult:
    ok: bool
    final_url: str
    title: str
    note: str = ""


async def check_login(
    *,
    state_path: Path,
    check_url: str,
    headless: bool,
    timeout_ms: int = 30_000,
) -> LoginCheckResult:
    if not check_url:
        return LoginCheckResult(ok=False, final_url="", title="", note="BB_COURSES_URL is empty; nothing to check.")
    if not state_path.exists():
        return LoginCheckResult(
            ok=False,
            final_url="",
            title="",
            note=f"storage_state not found: {state_path}",
        )

    try:
        from playwright.async_api import async_playwright
    except Exception as e:  # pragma: no cover
        return LoginCheckResult(ok=False, final_url="", title="", note=f"Playwright import failed: {e}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(storage_state=str(state_path))
        page = await context.new_page()
        try:
            await page.goto(check_url, wait_until="domcontentloaded", timeout=timeout_ms)
            title = await page.title()
            final_url = page.url
        finally:
            await context.close()
            await browser.close()

    ok = True
    note = ""
    lowered = final_url.lower()
    if "login" in lowered or "sso" in lowered:
        ok = False
        note = f"Redirected to a login-like URL: {final_url}"

    logger.info("login_check title=%r final_url=%s ok=%s", title, final_url, ok)
    return LoginCheckResult(ok=ok, final_url=final_url, title=title, note=note)

