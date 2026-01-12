from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app.bb.courses import Course, eval_courses_on_portal_page

logger = logging.getLogger(__name__)


def parse_assignment_info_html(*, html: str) -> dict:
    import html as html_mod
    import re
    from html.parser import HTMLParser

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

    # Unsubmitted/new-attempt view: meta labels.
    due_html = first_group(
        r'<div[^>]*class="metaLabel"[^>]*>\s*到期日期\s*</div>\s*<div[^>]*class="metaField"[^>]*>(.*?)</div>',
        html,
    )
    due_at_raw = text_from(html_mod.unescape(due_html)) if due_html else ""

    points_html = first_group(
        r'<div[^>]*class="metaLabel"[^>]*>\s*满分\s*</div>\s*<div[^>]*class="metaField"[^>]*>(.*?)</div>',
        html,
    )
    points_possible_raw = text_from(html_mod.unescape(points_html)) if points_html else ""

    # Submitted grading view: headings + pointsPossible spans.
    if not due_at_raw:
        due_txt = first_group(r"<h3>\s*到期日期\s*</h3>\s*<p>\s*(.*?)\s*</p>", html)
        due_at_raw = text_from(html_mod.unescape(due_txt)) if due_txt else ""

    points_possible = None
    m = re.search(r'class="pointsPossible"[^>]*>\s*/\s*([0-9]+(?:\.[0-9]+)?)', html, flags=re.I)
    if m:
        points_possible_raw = points_possible_raw or m.group(1).strip()

    if points_possible_raw:
        try:
            points_possible = int(points_possible_raw)
        except Exception:
            try:
                points_possible = float(points_possible_raw)
            except Exception:
                points_possible = None

    # Submitted grading view: grade values.
    grade_raw = first_group(r'<input[^>]*id="aggregateGrade"[^>]*value="([^"]*)"', html)
    attempt_grade_raw = first_group(r'<input[^>]*id="currentAttempt_grade"[^>]*value="([^"]*)"', html)

    def to_number(raw: str):
        val = (raw or "").strip()
        if not val or val in {"-", "—"}:
            return None
        try:
            return int(val)
        except Exception:
            try:
                return float(val)
            except Exception:
                return None

    return {
        "due_at_raw": due_at_raw,
        "points_possible_raw": points_possible_raw,
        "points_possible": points_possible,
        "grade_raw": grade_raw.strip() if grade_raw is not None else "",
        "grade": to_number(grade_raw),
        "attempt_grade_raw": attempt_grade_raw.strip() if attempt_grade_raw is not None else "",
        "attempt_grade": to_number(attempt_grade_raw),
    }


def extract_new_attempt_url(*, html: str, base_url: str) -> str:
    import html as html_mod
    import re
    from urllib.parse import urljoin

    raw = (
        re.search(
            r"document\.location\s*=\s*(?:\\)?'([^']*uploadAssignment\?action=newAttempt[^']*)'",
            html,
            flags=re.I,
        )
        or re.search(
            r'document\.location\s*=\s*(?:\\)?\"([^\"]*uploadAssignment\?action=newAttempt[^\"]*)\"',
            html,
            flags=re.I,
        )
    )
    if not raw:
        return ""
    href = html_mod.unescape(raw.group(1)).replace("&amp;", "&")
    return urljoin(base_url, href)


def parse_assignments_html(
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

    def resolve_url(href: str) -> str:
        if not href:
            return ""
        href = html_mod.unescape(href).replace("&amp;", "&")
        return urljoin(page_url or base_url or "", href)

    if not course_id:
        course_id = first_group(r'<input[^>]*id="course_id"[^>]*value="([^"]+)"', html)

    if not course_name:
        title = first_group(r"<title>(.*?)</title>", html)
        course_name = title.strip()

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

        # Prefer an online-submission link if present.
        submission_href = (
            first_group(r'<a[^>]*href="([^"]*/webapps/assignment/uploadAssignment[^"]*)"', li_html)
            or first_group(r"this\\.href='([^']*/webapps/assignment/uploadAssignment[^']*)'", li_html)
            or first_group(r'this\\.href=\"([^\"]*/webapps/assignment/uploadAssignment[^\"]*)\"', li_html)
        )
        submission_url = resolve_url(submission_href)

        href = (
            first_group(r"<h3[^>]*>.*?<a[^>]*href=\"([^\"]+)\"", li_html)
            or first_group(r"<a[^>]*href=\"([^\"]+)\"", li_html)
        )
        url = resolve_url(href)

        is_online_submission = "/webapps/assignment/uploadAssignment" in (submission_url or url)

        items.append(
            {
                "source": "assignment",
                "course_id": course_id,
                "course_name": course_name,
                "content_item_id": content_item_id,
                "title": title,
                "url": submission_url or url,
                "is_online_submission": is_online_submission,
                "submission_url": submission_url,
            }
        )

    return items


@dataclass(frozen=True)
class DebugAssignmentsResult:
    course: Course
    course_entry_url: str
    assignments_url: str
    items: list[dict]
    portal_html_path: Path
    course_entry_html_path: Path
    assignments_html_path: Path


async def debug_dump_assignments(
    *,
    state_path: Path,
    portal_url: str,
    course_query: str,
    headless: bool,
    portal_html_path: Path,
    course_entry_html_path: Path,
    assignments_html_path: Path,
    timeout_ms: int = 30_000,
) -> DebugAssignmentsResult:
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
    assignments_html_path.parent.mkdir(parents=True, exist_ok=True)

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
                r'<a[^>]*href="([^"]+)"[^>]*>\s*<span[^>]*title="课程作业"[^>]*>\s*课程作业\s*</span>\s*</a>',
                entry_html,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if not m:
                m = re.search(r'<a[^>]*href="([^"]+)"[^>]*>\s*<span[^>]*title="课程作业"', entry_html, flags=re.I)
            if not m:
                raise RuntimeError('cannot find the "课程作业" menu link in course entry HTML; inspect debug HTML.')

            assignments_href = m.group(1).replace("&amp;", "&")
            assignments_url = urljoin(course_entry_url, assignments_href)

            await page.goto(assignments_url, wait_until="domcontentloaded", timeout=timeout_ms)
            assignments_url = page.url
            html = await page.content()
            assignments_html_path.write_text(html, encoding="utf-8")
            logger.info("saved debug assignments html: %s (url=%s)", assignments_html_path, assignments_url)

            items = parse_assignments_html(
                html=html,
                page_url=assignments_url,
                base_url=portal_url,
                course_id=course.course_id,
                course_name=course.name,
            )
            logger.info("assignments parsed: %d", len(items))

            return DebugAssignmentsResult(
                course=course,
                course_entry_url=course_entry_url,
                assignments_url=assignments_url,
                items=items,
                portal_html_path=portal_html_path,
                course_entry_html_path=course_entry_html_path,
                assignments_html_path=assignments_html_path,
            )
        finally:
            await context.close()
            await browser.close()


@dataclass(frozen=True)
class DebugAssignmentSamplesResult:
    course: Course
    assignments_url: str
    submitted_title: str
    submitted_url: str
    submitted_html_path: Path
    submitted_info: dict
    submitted_new_attempt_url: str
    submitted_new_attempt_html_path: Path
    submitted_new_attempt_info: dict
    unsubmitted_title: str
    unsubmitted_url: str
    unsubmitted_html_path: Path
    unsubmitted_info: dict
    assignments_html_path: Path


async def debug_dump_assignment_samples(
    *,
    state_path: Path,
    portal_url: str,
    course_query: str,
    submitted_assignment_query: str,
    unsubmitted_assignment_query: str,
    headless: bool,
    assignments_html_path: Path,
    submitted_html_path: Path,
    submitted_new_attempt_html_path: Path,
    unsubmitted_html_path: Path,
    timeout_ms: int = 30_000,
) -> DebugAssignmentSamplesResult:
    if not portal_url:
        raise ValueError("BB_COURSES_URL is empty.")
    if not course_query:
        raise ValueError("course_query is empty.")
    if not submitted_assignment_query:
        raise ValueError("submitted_assignment_query is empty.")
    if not unsubmitted_assignment_query:
        raise ValueError("unsubmitted_assignment_query is empty.")
    if not state_path.exists():
        raise FileNotFoundError(f"storage_state not found: {state_path}")

    import re
    from urllib.parse import urljoin

    from playwright.async_api import async_playwright

    assignments_html_path.parent.mkdir(parents=True, exist_ok=True)
    submitted_html_path.parent.mkdir(parents=True, exist_ok=True)
    submitted_new_attempt_html_path.parent.mkdir(parents=True, exist_ok=True)
    unsubmitted_html_path.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(storage_state=str(state_path))
        page = await context.new_page()
        try:
            await page.goto(portal_url, wait_until="domcontentloaded", timeout=timeout_ms)
            courses = await eval_courses_on_portal_page(page=page)
            matched = [c for c in courses if course_query in c.name]
            if not matched:
                raise RuntimeError(f"course not found by query={course_query!r}; got {len(courses)} courses")
            course = matched[0]

            course_url = urljoin(portal_url, course.url)
            logger.info("target course matched: %s (course_id=%s)", course.name, course.course_id)
            await page.goto(course_url, wait_until="domcontentloaded", timeout=timeout_ms)

            entry_html = await page.content()
            menu_m = re.search(
                r'<a[^>]*href="([^"]+)"[^>]*>\s*<span[^>]*title="课程作业"[^>]*>\s*课程作业\s*</span>\s*</a>',
                entry_html,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if not menu_m:
                menu_m = re.search(r'<a[^>]*href="([^"]+)"[^>]*>\s*<span[^>]*title="课程作业"', entry_html, flags=re.I)
            if not menu_m:
                raise RuntimeError('cannot find the "课程作业" menu link in course entry HTML.')

            assignments_href = menu_m.group(1).replace("&amp;", "&")
            assignments_url = urljoin(page.url, assignments_href)

            await page.goto(assignments_url, wait_until="domcontentloaded", timeout=timeout_ms)
            assignments_url = page.url
            html = await page.content()
            assignments_html_path.write_text(html, encoding="utf-8")
            logger.info("saved debug assignments html: %s (url=%s)", assignments_html_path, assignments_url)

            items = parse_assignments_html(
                html=html,
                page_url=assignments_url,
                base_url=portal_url,
                course_id=course.course_id,
                course_name=course.name,
            )

            def pick(query: str) -> dict:
                hits = [it for it in items if query in (it.get("title") or "")]
                if not hits:
                    raise RuntimeError(f"assignment not found by query={query!r}; parsed={len(items)} items")
                return hits[0]

            submitted = pick(submitted_assignment_query)
            unsubmitted = pick(unsubmitted_assignment_query)

            submitted_url = str(submitted.get("url") or "")
            unsubmitted_url = str(unsubmitted.get("url") or "")
            if not submitted_url:
                raise RuntimeError(f"submitted assignment has empty url: {submitted.get('title')!r}")
            if not unsubmitted_url:
                raise RuntimeError(f"unsubmitted assignment has empty url: {unsubmitted.get('title')!r}")

            await page.goto(submitted_url, wait_until="domcontentloaded", timeout=timeout_ms)
            submitted_final_url = page.url
            submitted_html = await page.content()
            submitted_html_path.write_text(submitted_html, encoding="utf-8")
            logger.info("saved submitted assignment html: %s (url=%s)", submitted_html_path, submitted_final_url)

            submitted_info = parse_assignment_info_html(html=submitted_html)
            new_attempt_url = extract_new_attempt_url(html=submitted_html, base_url=submitted_final_url)
            new_attempt_info: dict = {}
            new_attempt_final_url = ""
            if new_attempt_url:
                await page.goto(new_attempt_url, wait_until="domcontentloaded", timeout=timeout_ms)
                new_attempt_final_url = page.url
                new_attempt_html = await page.content()
                submitted_new_attempt_html_path.write_text(new_attempt_html, encoding="utf-8")
                logger.info(
                    "saved submitted new-attempt html: %s (url=%s)", submitted_new_attempt_html_path, new_attempt_final_url
                )
                new_attempt_info = parse_assignment_info_html(html=new_attempt_html)

            await page.goto(unsubmitted_url, wait_until="domcontentloaded", timeout=timeout_ms)
            unsubmitted_final_url = page.url
            unsubmitted_html = await page.content()
            unsubmitted_html_path.write_text(unsubmitted_html, encoding="utf-8")
            logger.info("saved unsubmitted assignment html: %s (url=%s)", unsubmitted_html_path, unsubmitted_final_url)
            unsubmitted_info = parse_assignment_info_html(html=unsubmitted_html)

            return DebugAssignmentSamplesResult(
                course=course,
                assignments_url=assignments_url,
                submitted_title=str(submitted.get("title") or ""),
                submitted_url=submitted_final_url,
                submitted_html_path=submitted_html_path,
                submitted_info=submitted_info,
                submitted_new_attempt_url=new_attempt_final_url or new_attempt_url,
                submitted_new_attempt_html_path=submitted_new_attempt_html_path,
                submitted_new_attempt_info=new_attempt_info,
                unsubmitted_title=str(unsubmitted.get("title") or ""),
                unsubmitted_url=unsubmitted_final_url,
                unsubmitted_html_path=unsubmitted_html_path,
                unsubmitted_info=unsubmitted_info,
                assignments_html_path=assignments_html_path,
            )
        finally:
            await context.close()
            await browser.close()
