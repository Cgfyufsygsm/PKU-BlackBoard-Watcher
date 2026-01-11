from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app.bb.courses import Course, eval_courses_on_portal_page

logger = logging.getLogger(__name__)


def parse_teaching_content_html(
    *,
    html: str,
    page_url: str = "",
    base_url: str = "",
    course_id: str = "",
    course_name: str = "",
) -> list[dict]:
    import html as html_mod
    import re
    from html.parser import HTMLParser
    from urllib.parse import urljoin

    class _Text(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.parts: list[str] = []

        def handle_data(self, data: str) -> None:
            if data:
                self.parts.append(data)

        def get(self) -> str:
            return " ".join(" ".join(self.parts).split()).strip()

    def text_from(fragment: str) -> str:
        parser = _Text()
        parser.feed(fragment)
        return parser.get()

    def first_group(pattern: str, s: str) -> str:
        m = re.search(pattern, s, flags=re.IGNORECASE | re.DOTALL)
        return m.group(1).strip() if m else ""

    if not course_id:
        course_id = first_group(r'<input[^>]*id="course_id"[^>]*value="([^"]+)"', html)

    if not course_name:
        title = first_group(r"<title>(.*?)</title>", html)
        course_name = title.strip()

    # Blackboard "教学内容" list typically has li items like:
    # <li id="contentListItem:_xxxxx_1" class="liItem"> ... </li>
    # We keep it conservative and match those list items.
    li_re = re.compile(
        r'<li[^>]*id="contentListItem:([^"]+)"[^>]*>(.*?)</li>',
        flags=re.IGNORECASE | re.DOTALL,
    )
    items: list[dict] = []
    for m in li_re.finditer(html):
        content_item_id, li_html = m.group(1), m.group(2)

        title_html = first_group(r"<h3[^>]*>(.*?)</h3>", li_html) or first_group(r"<a[^>]*href=\"[^\"]+\"[^>]*>(.*?)</a>", li_html)
        title = text_from(html_mod.unescape(title_html))
        if not title:
            continue

        href = (
            first_group(r'<div[^>]*class="[^"]*item[^"]*"[^>]*>.*?<a[^>]*href="([^"]+)"', li_html)
            or first_group(r"<h3[^>]*>.*?<a[^>]*href=\"([^\"]+)\"", li_html)
            or first_group(r"<a[^>]*href=\"([^\"]+)\"", li_html)
        )
        url = ""
        if href:
            url = urljoin(page_url or base_url or "", html_mod.unescape(href))

        body_html = first_group(r'<div[^>]*class="[^"]*vtbegenerated[^"]*"[^>]*>(.*?)</div>', li_html)
        content = text_from(html_mod.unescape(body_html))

        has_attachments = bool(re.search(r"/bbcswebdav/|/webapps/blackboard/execute/content/file\\?", li_html))

        items.append(
            {
                "source": "teaching_content",
                "course_id": course_id,
                "course_name": course_name,
                "content_item_id": content_item_id,
                "title": title,
                "content": content,
                "has_attachments": has_attachments,
                "url": url,
            }
        )

    return items


@dataclass(frozen=True)
class DebugTeachingContentResult:
    course: Course
    course_entry_url: str
    teaching_content_url: str
    items: list[dict]
    portal_html_path: Path
    course_entry_html_path: Path
    teaching_content_html_path: Path


async def debug_dump_teaching_content(
    *,
    state_path: Path,
    portal_url: str,
    course_query: str,
    headless: bool,
    portal_html_path: Path,
    course_entry_html_path: Path,
    teaching_content_html_path: Path,
    timeout_ms: int = 30_000,
) -> DebugTeachingContentResult:
    if not portal_url:
        raise ValueError("BB_COURSES_URL is empty.")
    if not course_query:
        raise ValueError("course_query is empty.")
    if not state_path.exists():
        raise FileNotFoundError(f"storage_state not found: {state_path}")

    import re
    from urllib.parse import urljoin

    from playwright.async_api import async_playwright

    portal_html_path.parent.mkdir(parents=True, exist_ok=True)
    course_entry_html_path.parent.mkdir(parents=True, exist_ok=True)
    teaching_content_html_path.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(storage_state=str(state_path))
        page = await context.new_page()
        try:
            await page.goto(portal_url, wait_until="domcontentloaded", timeout=timeout_ms)
            portal_html_path.write_text(await page.content(), encoding="utf-8")
            logger.info("saved debug portal html: %s", portal_html_path)

            courses = await eval_courses_on_portal_page(page=page)
            matched = [c for c in courses if course_query in c.name]
            if not matched:
                raise RuntimeError(f"course not found by query={course_query!r}; got {len(courses)} courses")
            course = matched[0]
            course_url = urljoin(portal_url, course.url)
            logger.info("target course matched: %s (course_id=%s)", course.name, course.course_id)

            await page.goto(course_url, wait_until="domcontentloaded", timeout=timeout_ms)
            course_entry_url = page.url
            entry_html = await page.content()
            course_entry_html_path.write_text(entry_html, encoding="utf-8")
            logger.info("saved debug course entry html: %s (url=%s)", course_entry_html_path, course_entry_url)

            # Extract the left-menu link for “教学内容” from the current page HTML.
            m = re.search(
                r'<a[^>]*href="([^"]+)"[^>]*>\s*<span[^>]*title="教学内容"[^>]*>\s*教学内容\s*</span>\s*</a>',
                entry_html,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if not m:
                m = re.search(r'<a[^>]*href="([^"]+)"[^>]*>\s*<span[^>]*title="教学内容"', entry_html, flags=re.I)
            if not m:
                raise RuntimeError('cannot find the "教学内容" menu link in course entry HTML; inspect debug HTML.')

            teaching_href = m.group(1).replace("&amp;", "&")
            teaching_content_url = urljoin(course_entry_url, teaching_href)

            await page.goto(teaching_content_url, wait_until="domcontentloaded", timeout=timeout_ms)
            teaching_content_url = page.url
            content_html = await page.content()
            teaching_content_html_path.write_text(content_html, encoding="utf-8")
            logger.info("saved debug teaching content html: %s (url=%s)", teaching_content_html_path, teaching_content_url)

            items = parse_teaching_content_html(
                html=content_html,
                page_url=teaching_content_url,
                base_url=portal_url,
                course_id=course.course_id,
                course_name=course.name,
            )
            logger.info("teaching content items parsed: %d", len(items))

            return DebugTeachingContentResult(
                course=course,
                course_entry_url=course_entry_url,
                teaching_content_url=teaching_content_url,
                items=items,
                portal_html_path=portal_html_path,
                course_entry_html_path=course_entry_html_path,
                teaching_content_html_path=teaching_content_html_path,
            )
        finally:
            await context.close()
            await browser.close()
