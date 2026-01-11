from __future__ import annotations

from pathlib import Path


async def export_storage_state(
    *,
    login_url: str,
    state_path: Path,
    headless: bool = False,
) -> None:
    if not login_url:
        raise ValueError("BB_LOGIN_URL is empty.")

    try:
        from playwright.async_api import async_playwright
    except Exception as e:  # pragma: no cover
        raise RuntimeError(f"Playwright import failed: {e}") from e

    state_path.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(login_url, wait_until="domcontentloaded")

        print("")
        print("1) Please finish login in the opened browser window.")
        print(f"2) Then press Enter here to save storage state to: {state_path}")
        input("> ")

        await context.storage_state(path=str(state_path))
        await context.close()
        await browser.close()

