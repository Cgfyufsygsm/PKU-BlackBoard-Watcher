from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app.bb.announcements import parse_announcements_html
from app.bb.assignments import parse_assignments_html
from app.bb.courses import Course, eval_courses_on_portal_page
from app.bb.grades import parse_grades_html
from app.bb.teaching_content import parse_teaching_content_html
from app.models import Item

logger = logging.getLogger(__name__)


def _as_item(d: dict) -> Item:
    source = (d.get("source") or "").strip()
    course_id = (d.get("course_id") or "").strip()
    course_name = (d.get("course_name") or "").strip()
    title = (d.get("title") or "").strip()
    url = (d.get("url") or "").strip()

    external_id = ""
    if source == "announcement":
        external_id = d.get("announcement_id", "") or ""
        ts = d.get("published_at", "") or ""
        due = ""
    elif source == "teaching_content":
        external_id = d.get("content_item_id", "") or ""
        ts = ""
        due = ""
    elif source == "assignment":
        external_id = d.get("content_item_id", "") or ""
        ts = d.get("published_at", "") or ""
        due = d.get("due_at", "") or d.get("due_at_raw", "") or ""
    elif source == "grade_item":
        external_id = d.get("row_id", "") or ""
        ts = d.get("lastactivity", "") or ""
        due = d.get("duedate", "") or d.get("duedate_display", "") or ""
    else:
        ts = ""
        due = ""

    return Item(
        source=source,
        course_id=course_id,
        course_name=course_name,
        title=title,
        url=url,
        due=due or None,
        ts=ts or None,
        external_id=external_id or None,
        raw=d,
    )


def _find_menu_href(entry_html: str, menu_titles: list[str]) -> str:
    import re

    for menu_title in menu_titles:
        m = re.search(
            rf'<a[^>]*href="([^"]+)"[^>]*>\s*<span[^>]*title="{re.escape(menu_title)}"[^>]*>\s*{re.escape(menu_title)}\s*</span>\s*</a>',
            entry_html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not m:
            m = re.search(rf'<a[^>]*href="([^"]+)"[^>]*>\s*<span[^>]*title="{re.escape(menu_title)}"', entry_html, flags=re.I)
        if m:
            return m.group(1).replace("&amp;", "&")
    return ""


@dataclass(frozen=True)
class FetchAllResult:
    courses: list[Course]
    items: list[Item]
    errors: list[dict]


async def fetch_all_items(
    *,
    state_path: Path,
    portal_url: str,
    headless: bool,
    timeout_ms: int = 45_000,
    course_limit: int = 0,
) -> FetchAllResult:
    if not portal_url:
        raise ValueError("BB_COURSES_URL is empty.")
    if not state_path.exists():
        raise FileNotFoundError(f"storage_state not found: {state_path}")

    from urllib.parse import urljoin

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(storage_state=str(state_path))
        page = await context.new_page()
        try:
            await page.goto(portal_url, wait_until="domcontentloaded", timeout=timeout_ms)
            courses = await eval_courses_on_portal_page(page=page)
            if course_limit and course_limit > 0:
                courses = courses[:course_limit]
            logger.info("courses to fetch: %d", len(courses))

            all_items: list[Item] = []
            errors: list[dict] = []

            for course in courses:
                course_url = urljoin(portal_url, course.url)
                try:
                    await page.goto(course_url, wait_until="domcontentloaded", timeout=timeout_ms)
                    await page.wait_for_timeout(300)
                    course_entry_url = page.url
                    entry_html = await page.content()

                    # 1) Announcements: course entry URL is already in announcements context.
                    try:
                        anns = parse_announcements_html(
                            html=entry_html,
                            page_url=course_entry_url,
                            base_url=portal_url,
                            course_id=course.course_id,
                            course_name=course.name,
                        )
                        all_items.extend(_as_item(d) for d in anns)
                    except Exception as e:
                        errors.append(
                            {"course_id": course.course_id, "course_name": course.name, "board": "announcement", "error": repr(e)}
                        )

                    # 2) Teaching content
                    teaching_href = _find_menu_href(entry_html, ["教学内容", "课程内容", "Course Content"])
                    if teaching_href:
                        try:
                            teaching_url = urljoin(course_entry_url, teaching_href)
                            await page.goto(teaching_url, wait_until="domcontentloaded", timeout=timeout_ms)
                            await page.wait_for_timeout(300)
                            teaching_html = await page.content()
                            tc = parse_teaching_content_html(
                                html=teaching_html,
                                page_url=page.url,
                                base_url=portal_url,
                                course_id=course.course_id,
                                course_name=course.name,
                            )
                            all_items.extend(_as_item(d) for d in tc)
                        except Exception as e:
                            errors.append(
                                {
                                    "kind": "exception",
                                    "course_id": course.course_id,
                                    "course_name": course.name,
                                    "board": "teaching_content",
                                    "error": repr(e),
                                }
                            )
                    else:
                        errors.append(
                            {
                                "kind": "missing_menu",
                                "course_id": course.course_id,
                                "course_name": course.name,
                                "board": "teaching_content",
                                "error": "menu link not found",
                            }
                        )

                    # 3) Assignments
                    assignments_href = _find_menu_href(entry_html, ["课程作业", "作业", "Assignments"])
                    if assignments_href:
                        try:
                            assignments_url = urljoin(course_entry_url, assignments_href)
                            await page.goto(assignments_url, wait_until="domcontentloaded", timeout=timeout_ms)
                            await page.wait_for_timeout(300)
                            assignments_html = await page.content()
                            ass = parse_assignments_html(
                                html=assignments_html,
                                page_url=page.url,
                                base_url=portal_url,
                                course_id=course.course_id,
                                course_name=course.name,
                            )
                            all_items.extend(_as_item(d) for d in ass)
                        except Exception as e:
                            errors.append(
                                {"kind": "exception", "course_id": course.course_id, "course_name": course.name, "board": "assignments", "error": repr(e)}
                            )
                    else:
                        errors.append(
                            {
                                "kind": "missing_menu",
                                "course_id": course.course_id,
                                "course_name": course.name,
                                "board": "assignments",
                                "error": "menu link not found",
                            }
                        )

                    # 4) Grades
                    grades_href = _find_menu_href(entry_html, ["个人成绩", "成绩", "My Grades"])
                    if grades_href:
                        try:
                            grades_url = urljoin(course_entry_url, grades_href)
                            await page.goto(grades_url, wait_until="domcontentloaded", timeout=timeout_ms)
                            await page.wait_for_timeout(300)
                            grades_html = await page.content()
                            gi = parse_grades_html(
                                html=grades_html,
                                base_url=portal_url,
                                course_id=course.course_id,
                                course_name=course.name,
                            )
                            all_items.extend(_as_item(d) for d in gi)
                        except Exception as e:
                            errors.append({"kind": "exception", "course_id": course.course_id, "course_name": course.name, "board": "grades", "error": repr(e)})
                    else:
                        errors.append({"kind": "missing_menu", "course_id": course.course_id, "course_name": course.name, "board": "grades", "error": "menu link not found"})

                    logger.info(
                        "fetched course: %s (course_id=%s) total_items=%d",
                        course.name,
                        course.course_id,
                        len(all_items),
                    )
                except Exception as e:
                    errors.append({"kind": "exception", "course_id": course.course_id, "course_name": course.name, "board": "course", "error": repr(e)})
                    continue

            return FetchAllResult(courses=courses, items=all_items, errors=errors)
        finally:
            await context.close()
            await browser.close()
