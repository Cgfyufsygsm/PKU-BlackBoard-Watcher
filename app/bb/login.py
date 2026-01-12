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


@dataclass(frozen=True)
class LoginRefreshResult:
    ok: bool
    final_url: str
    note: str = ""


async def refresh_storage_state_with_credentials(
    *,
    state_path: Path,
    login_url: str,
    verify_url: str,
    username: str,
    password: str,
    headless: bool,
    timeout_ms: int = 45_000,
) -> LoginRefreshResult:
    """
    Best-effort auto login flow.

    This assumes the upstream SSO does not require captcha/2FA. If it does, this will fail and the caller
    should fall back to manual `scripts/export_state.py`.
    """
    if not login_url:
        return LoginRefreshResult(ok=False, final_url="", note="BB_LOGIN_URL is empty.")
    if not verify_url:
        return LoginRefreshResult(ok=False, final_url="", note="BB_COURSES_URL is empty; cannot verify login.")
    if not username or not password:
        return LoginRefreshResult(ok=False, final_url="", note="BB_USERNAME/BB_PASSWORD is empty.")

    try:
        from playwright.async_api import async_playwright
    except Exception as e:  # pragma: no cover
        return LoginRefreshResult(ok=False, final_url="", note=f"Playwright import failed: {e}")

    state_path.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context()
        page = await context.new_page()
        try:
            await page.goto(login_url, wait_until="domcontentloaded", timeout=timeout_ms)

            async def maybe_fill_login_form() -> bool:
                # Try a set of common selectors used by CAS/IdP login pages.
                user_selectors = [
                    'input[name="username"]',
                    'input#username',
                    'input[name="userName"]',
                    'input[name="user"]',
                    'input[type="text"]',
                ]
                pass_selectors = [
                    'input[name="password"]',
                    'input#password',
                    'input[name="pass"]',
                    'input[type="password"]',
                ]
                submit_selectors = [
                    'button[type="submit"]',
                    'input[type="submit"]',
                    'button:has-text("登录")',
                    'button:has-text("Log In")',
                    'button:has-text("Sign in")',
                ]

                user_locator = None
                for sel in user_selectors:
                    loc = page.locator(sel).first
                    if await loc.count():
                        user_locator = loc
                        break
                pass_locator = None
                for sel in pass_selectors:
                    loc = page.locator(sel).first
                    if await loc.count():
                        pass_locator = loc
                        break
                if user_locator is None or pass_locator is None:
                    return False

                await user_locator.fill(username)
                await pass_locator.fill(password)

                for sel in submit_selectors:
                    btn = page.locator(sel).first
                    if await btn.count():
                        await btn.click()
                        return True

                # Fallback: press Enter on password field.
                await pass_locator.press("Enter")
                return True

            filled = await maybe_fill_login_form()
            if filled:
                # Wait for navigation/redirect chain.
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
                except Exception:
                    pass

            # Verify by opening a URL that requires authentication.
            await page.goto(verify_url, wait_until="domcontentloaded", timeout=timeout_ms)
            final_url = page.url
            lowered = final_url.lower()
            if "login" in lowered or "sso" in lowered:
                return LoginRefreshResult(ok=False, final_url=final_url, note="still redirected to login after credential submit")

            # Persist storage state.
            await context.storage_state(path=str(state_path))
            return LoginRefreshResult(ok=True, final_url=final_url, note="storage_state refreshed")
        finally:
            await context.close()
            await browser.close()


async def ensure_login(
    *,
    state_path: Path,
    login_url: str,
    verify_url: str,
    headless: bool,
    username: str = "",
    password: str = "",
    timeout_ms: int = 45_000,
) -> LoginCheckResult:
    """
    Ensure storage_state is valid.
    - First check with existing state_path
    - If invalid and credentials provided, refresh storage_state automatically
    - Re-check and return the final result
    """
    check = await check_login(state_path=state_path, check_url=verify_url, headless=headless, timeout_ms=timeout_ms)
    if check.ok:
        return check

    if username and password:
        logger.warning("login state invalid; attempting auto refresh with BB_USERNAME/BB_PASSWORD")
        refreshed = await refresh_storage_state_with_credentials(
            state_path=state_path,
            login_url=login_url,
            verify_url=verify_url,
            username=username,
            password=password,
            headless=headless,
            timeout_ms=timeout_ms,
        )
        if refreshed.ok:
            return await check_login(state_path=state_path, check_url=verify_url, headless=headless, timeout_ms=timeout_ms)
        logger.error("auto refresh failed: %s", refreshed.note)

    return check
