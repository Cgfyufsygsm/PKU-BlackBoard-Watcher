from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app.bb.courses import Course, eval_courses_on_portal_page

logger = logging.getLogger(__name__)


def parse_announcements_html(
    *,
    html: str,
    page_url: str = "",
    base_url: str = "",
    course_id: str = "",
    course_name: str = "",
) -> list[dict]:
    import html as html_mod
    import re
    from datetime import datetime, timedelta, timezone
    from html.parser import HTMLParser

    class _Text(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.parts: list[str] = []

        def handle_data(self, data: str) -> None:  # noqa: D401
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

    def normalize_bb_cn_datetime(raw: str) -> str:
        text = " ".join((raw or "").split()).strip()
        if not text:
            return ""

        m = re.search(
            r"(?P<y>\d{4})年(?P<m>\d{1,2})月(?P<d>\d{1,2})日\s+"
            r"(?:星期[一二三四五六日天]\s+)?"
            r"(?P<ampm>上午|下午|中午|晚上)?"
            r"(?P<h>\d{1,2})时(?P<mi>\d{1,2})分(?P<s>\d{1,2})秒"
            r"(?:\s+(?P<tz>[A-Za-z]{2,5}))?",
            text,
        )
        if not m:
            return ""

        year = int(m.group("y"))
        month = int(m.group("m"))
        day = int(m.group("d"))
        hour = int(m.group("h"))
        minute = int(m.group("mi"))
        second = int(m.group("s"))
        ampm = (m.group("ampm") or "").strip()

        if ampm in {"下午", "晚上"} and hour < 12:
            hour += 12
        elif ampm == "上午" and hour == 12:
            hour = 0
        elif ampm == "中午" and hour < 11:
            hour += 12

        tzinfo = timezone(timedelta(hours=8))
        dt = datetime(year, month, day, hour, minute, second, tzinfo=tzinfo)
        return dt.isoformat()

    detected_course_id = first_group(r'<input[^>]*id="course_id"[^>]*value="([^"]+)"', html)
    if not course_id:
        course_id = detected_course_id

    if not course_name:
        title = first_group(r"<title>(.*?)</title>", html)
        if "–" in title:
            course_name = title.split("–", 1)[1].strip()
        else:
            course_name = title.strip()

    ul = first_group(r'(<ul[^>]*id="announcementList"[^>]*>.*?</ul>)', html)
    if not ul:
        return []

    items: list[dict] = []
    li_re = re.compile(
        r'<li[^>]*class="[^"]*clearfix[^"]*"[^>]*id="([^"]+)"[^>]*>(.*?)</li>',
        flags=re.IGNORECASE | re.DOTALL,
    )
    for m in li_re.finditer(ul):
        announcement_id, li_html = m.group(1), m.group(2)
        title_html = first_group(r'<h3[^>]*class="[^"]*item[^"]*"[^>]*>(.*?)</h3>', li_html)
        title = text_from(html_mod.unescape(title_html))

        published_raw = first_group(r"发布时间:\s*([^<]+)</span>", li_html)
        published_at_raw = published_raw.strip()
        published_at = normalize_bb_cn_datetime(published_at_raw)

        content_html = first_group(r'<div[^>]*class="[^"]*vtbegenerated[^"]*"[^>]*>(.*?)</div>', li_html)
        content = text_from(html_mod.unescape(content_html))

        author_raw = first_group(r"发帖者:\s*</span>\s*([^<]+)</p>", li_html)
        author = author_raw.strip()

        url = page_url
        if not url and base_url and course_id:
            url = (
                base_url.rstrip("/")
                + "/webapps/blackboard/execute/announcement?method=search&context=course_entry"
                + f"&course_id={course_id}&handle=announcements_entry&mode=view"
            )
        if url and announcement_id:
            url = url.split("#", 1)[0] + "#" + announcement_id

        items.append(
            {
                "source": "announcement",
                "course_id": course_id,
                "course_name": course_name,
                "announcement_id": announcement_id,
                "title": title,
                "content": content,
                "published_at": published_at,
                "published_at_raw": published_at_raw,
                "author": author,
                "url": url,
            }
        )

    return items


@dataclass(frozen=True)
class DebugAnnouncementsResult:
    course: Course
    course_entry_url: str
    announcements_url: str
    announcements: list[dict]
    portal_html_path: Path
    course_entry_html_path: Path
    announcements_html_path: Path


async def debug_dump_course_announcements(
    *,
    state_path: Path,
    portal_url: str,
    course_query: str,
    headless: bool,
    portal_html_path: Path,
    course_entry_html_path: Path,
    announcements_html_path: Path,
    timeout_ms: int = 30_000,
) -> DebugAnnouncementsResult:
    if not portal_url:
        raise ValueError("BB_COURSES_URL is empty.")
    if not course_query:
        raise ValueError("course_query is empty.")
    if not state_path.exists():
        raise FileNotFoundError(f"storage_state not found: {state_path}")

    from urllib.parse import urljoin

    from playwright.async_api import async_playwright

    portal_html_path.parent.mkdir(parents=True, exist_ok=True)
    course_entry_html_path.parent.mkdir(parents=True, exist_ok=True)
    announcements_html_path.parent.mkdir(parents=True, exist_ok=True)

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
            course_entry_html_path.write_text(await page.content(), encoding="utf-8")
            logger.info("saved debug course entry html: %s (url=%s)", course_entry_html_path, course_entry_url)

            announcements_url = page.url
            html = await page.content()
            announcements_html_path.write_text(html, encoding="utf-8")
            logger.info("saved debug announcements html: %s (url=%s)", announcements_html_path, announcements_url)
            announcements = parse_announcements_html(
                html=html,
                page_url=announcements_url,
                course_id=course.course_id,
                course_name=course.name,
            )

            return DebugAnnouncementsResult(
                course=course,
                course_entry_url=course_entry_url,
                announcements_url=announcements_url,
                announcements=announcements,
                portal_html_path=portal_html_path,
                course_entry_html_path=course_entry_html_path,
                announcements_html_path=announcements_html_path,
            )
        finally:
            await context.close()
            await browser.close()

