from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app.bb.courses import Course, eval_courses_on_portal_page

logger = logging.getLogger(__name__)


def parse_grades_html(
    *,
    html: str,
    base_url: str = "",
    course_id: str = "",
    course_name: str = "",
) -> list[dict]:
    import html as html_mod
    import re
    from datetime import datetime, timedelta, timezone
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

    def parse_ms(raw: str) -> int | None:
        raw = (raw or "").strip()
        if not raw:
            return None
        try:
            v = int(raw)
        except Exception:
            return None
        if v <= 0:
            return None
        # Blackboard uses MAX_LONG for calculated rows.
        if v >= 9_000_000_000_000_000_000:
            return None
        return v

    def ms_to_iso(ms: int | None) -> str:
        if ms is None:
            return ""
        tzinfo = timezone(timedelta(hours=8))
        return datetime.fromtimestamp(ms / 1000.0, tz=tzinfo).isoformat()

    if not course_id:
        course_id = first_group(r"course_id=(_\d+_\d+)", html)
        if not course_id:
            course_id = first_group(r'var\s+course_id\s*=\s*"([^"]+)"', html)

    if not course_name:
        title = first_group(r"<title>(.*?)</title>", html)
        course_name = title.strip()

    # Locate each grade row by start indices.
    starts = [m.start() for m in re.finditer(r'<div\s+id="\d+"[^>]*\srole="row"', html, flags=re.I)]
    if not starts:
        return []
    starts.append(len(html))

    items: list[dict] = []
    for i in range(len(starts) - 1):
        seg = html[starts[i] : starts[i + 1]]

        row_id = first_group(r'<div\s+id="(\d+)"', seg)
        lastactivity_ms = parse_ms(first_group(r'lastactivity="(\d+)"', seg))
        duedate_ms = parse_ms(first_group(r'duedate="(\d+)"', seg))

        items_col = first_group(
            r"<!--\s*Items Column\s*-->\s*<div class=\"cell gradable\"[^>]*>(.*?)<!--\s*Activity Column\s*-->",
            seg,
        )
        a_tag = first_group(r"(<a\b[^>]*>.*?</a>)", items_col)
        href_raw = first_group(r'href="([^"]+)"', a_tag)
        onclick_raw = first_group(r'onclick="([^"]+)"', a_tag)
        load_frame_path = first_group(r"loadContentFrame\('([^']+)'\)", onclick_raw) or first_group(
            r'loadContentFrame\("([^"]+)"\)', onclick_raw
        )
        url_raw = html_mod.unescape(href_raw or load_frame_path)
        url = urljoin(base_url, url_raw) if (base_url and url_raw) else (url_raw or "")

        title_html = first_group(r"<a[^>]*>(.*?)</a>", items_col) or first_group(r"<span[^>]*>(.*?)</span>", items_col)
        title = text_from(html_mod.unescape(title_html))

        item_cat_html = first_group(r'<div class="itemCat"[^>]*>(.*?)</div>', items_col)
        item_cat = text_from(html_mod.unescape(item_cat_html))

        due_display = ""
        due_display_raw = first_group(r"到期日期:\s*([0-9]{4}-[0-9]{1,2}-[0-9]{1,2})", items_col)
        if due_display_raw:
            due_display = due_display_raw

        activity_col = first_group(
            r"<!--\s*Activity Column\s*-->\s*<div class=\"cell activity[^>]*>(.*?)<!--\s*Grade Column\s*-->",
            seg,
        )
        last_activity_display_html = first_group(r'<span class="lastActivityDate"[^>]*>(.*?)</span>', activity_col)
        last_activity_display = text_from(html_mod.unescape(last_activity_display_html))
        status_html = first_group(r'<span class="activityType"[^>]*>(.*?)</span>', activity_col)
        status = text_from(html_mod.unescape(status_html))

        grade_col = first_group(
            r"<!--\s*Grade Column\s*-->\s*<div class=\"cell grade\"[^>]*>(.*?)<!--\s*Status Column\s*-->",
            seg,
        )
        grade_html = first_group(r'<span class="grade"[^>]*>(.*?)</span>', grade_col)
        grade_raw = text_from(html_mod.unescape(grade_html))
        points_html = first_group(r'<span class="pointsPossible[^"]*"[^>]*>(.*?)</span>', grade_col)
        points_raw = text_from(html_mod.unescape(points_html)).lstrip("/").strip()

        def to_number(raw: str) -> int | float | None:
            val = (raw or "").strip().replace(",", "")
            if not val or val in {"-", "—"}:
                return None
            try:
                return int(val)
            except Exception:
                try:
                    return float(val)
                except Exception:
                    return None

        def grade_value(raw: str) -> int | float | str | None:
            """
            Blackboard grades can be:
            - numbers: "95", "100.00"
            - missing: "-", "—"
            - status/text: "否", "已提交", etc.
            """
            cleaned = (raw or "").strip()
            if not cleaned or cleaned in {"-", "—"}:
                return None
            numeric = to_number(cleaned)
            return numeric if numeric is not None else cleaned

        item = {
            "source": "grade_item",
            "course_id": course_id,
            "course_name": course_name,
            "row_id": row_id,
            "title": title,
            "category": item_cat,
            "url": url,
            "status": status,
            "grade_raw": grade_raw,
            "grade": grade_value(grade_raw),
            "points_possible_raw": points_raw,
            "points_possible": to_number(points_raw),
            "lastactivity_ms": lastactivity_ms,
            "lastactivity": ms_to_iso(lastactivity_ms),
            "lastactivity_display": last_activity_display,
            "duedate_ms": duedate_ms,
            "duedate": ms_to_iso(duedate_ms),
            "duedate_display": due_display,
        }
        # Filter out empty/non-row artifacts.
        if item["row_id"] and item["title"]:
            items.append(item)

    return items


@dataclass(frozen=True)
class DebugGradesResult:
    course: Course
    course_entry_url: str
    grades_url: str
    grades: list[dict]
    portal_html_path: Path
    course_entry_html_path: Path
    grades_html_path: Path


async def debug_dump_grades(
    *,
    state_path: Path,
    portal_url: str,
    course_query: str,
    headless: bool,
    portal_html_path: Path,
    course_entry_html_path: Path,
    grades_html_path: Path,
    timeout_ms: int = 45_000,
) -> DebugGradesResult:
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
    grades_html_path.parent.mkdir(parents=True, exist_ok=True)

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

            m = re.search(
                r'<a[^>]*href="([^"]+)"[^>]*>\s*<span[^>]*title="个人成绩"[^>]*>\s*个人成绩\s*</span>\s*</a>',
                entry_html,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if not m:
                m = re.search(r'<a[^>]*href="([^"]+)"[^>]*>\s*<span[^>]*title="个人成绩"', entry_html, flags=re.I)
            if not m:
                raise RuntimeError('cannot find the "个人成绩" menu link in course entry HTML; inspect debug HTML.')

            grades_href = m.group(1).replace("&amp;", "&")
            grades_url = urljoin(course_entry_url, grades_href)

            await page.goto(grades_url, wait_until="domcontentloaded", timeout=timeout_ms)
            await page.wait_for_timeout(800)
            grades_url = page.url
            html = await page.content()
            grades_html_path.write_text(html, encoding="utf-8")
            logger.info("saved debug grades html: %s (url=%s)", grades_html_path, grades_url)

            return DebugGradesResult(
                course=course,
                course_entry_url=course_entry_url,
                grades_url=grades_url,
                grades=parse_grades_html(
                    html=html,
                    base_url=portal_url,
                    course_id=course.course_id,
                    course_name=course.name,
                ),
                portal_html_path=portal_html_path,
                course_entry_html_path=course_entry_html_path,
                grades_html_path=grades_html_path,
            )
        finally:
            await context.close()
            await browser.close()
