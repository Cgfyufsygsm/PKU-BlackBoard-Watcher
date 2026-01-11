from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_COURSE_EXTRACT_SCRIPT = r"""
() => {
  const roleText = "在以下课程中，您是学生";
  const otherRoleTexts = [
    "在以下课程中，您是教师",
    "在以下课程中，您是助教",
    "在以下课程中，您是讲师",
  ];

  const isCourseLink = (href) => {
    if (!href) return false;
    return href.includes("type=Course") ||
      href.includes("/webapps/blackboard/") ||
      href.includes("course_id=") ||
      href.includes("courseId=") ||
      href.includes("Course&id=");
  };

  const uniq = (items) => {
    const seen = new Set();
    const out = [];
    for (const it of items) {
      const key = it.url;
      if (!key || seen.has(key)) continue;
      seen.add(key);
      out.push(it);
    }
    return out;
  };

  const allCourseLinks = () => {
    const links = Array.from(document.querySelectorAll("a"))
      .map((a) => ({ name: (a.innerText || "").trim(), url: a.href }))
      .filter((x) => x.name && isCourseLink(x.url));
    return uniq(links);
  };

  const findRoleLabel = () => {
    const nodes = Array.from(document.querySelectorAll("body *"))
      .filter((el) => el.childElementCount === 0);
    for (const el of nodes) {
      const txt = (el.textContent || "");
      if (txt.includes(roleText)) return el;
    }
    return null;
  };

  const extractAfterRoleLabel = (label) => {
    if (!label) return { note: "role label not found", courses: [] };

    const shouldStop = (el) => {
      if (el.childElementCount !== 0) return false;
      const txt = (el.textContent || "");
      return otherRoleTexts.some((t) => txt.includes(t));
    };

    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
    walker.currentNode = label;
    const courses = [];
    while (walker.nextNode()) {
      const el = walker.currentNode;
      if (shouldStop(el)) break;
      if (el.tagName === "A") {
        const name = (el.innerText || "").trim();
        const url = el.href;
        if (name && isCourseLink(url)) courses.push({ name, url });
      }
    }
    return { note: "extracted by scanning after role label", courses: uniq(courses) };
  };

  const label = findRoleLabel();
  const scanned = extractAfterRoleLabel(label);
  if (scanned.courses && scanned.courses.length) return scanned;
  if (!label) return { note: "role label not found; fallback to global link scan", courses: allCourseLinks() };

  let container = label;
  for (let i = 0; i < 6 && container; i++) {
    const links = Array.from(container.querySelectorAll("a"))
      .map((a) => ({ name: (a.innerText || "").trim(), url: a.href }))
      .filter((x) => x.name && isCourseLink(x.url));
    const courses = uniq(links);
    if (courses.length) {
      return { note: "extracted from role container", courses };
    }
    container = container.parentElement;
  }

  return { note: "role label found but no course links nearby; fallback to global link scan", courses: allCourseLinks() };
}
"""


@dataclass(frozen=True)
class Course:
    name: str
    url: str
    course_id: str = ""


def extract_course_id(url: str) -> str:
    import re

    for pattern in (r"key=(_\d+_\d+)", r"course_id=(_\d+_\d+)"):
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    return ""


async def fetch_courses_from_portal(
    *,
    state_path: Path,
    portal_url: str,
    headless: bool,
    debug_html_path: Path,
    timeout_ms: int = 30_000,
) -> list[Course]:
    if not portal_url:
        raise ValueError("BB_COURSES_URL is empty.")
    if not state_path.exists():
        raise FileNotFoundError(f"storage_state not found: {state_path}")

    from playwright.async_api import async_playwright

    debug_html_path.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(storage_state=str(state_path))
        page = await context.new_page()
        try:
            await page.goto(portal_url, wait_until="domcontentloaded", timeout=timeout_ms)
            html = await page.content()
            debug_html_path.write_text(html, encoding="utf-8")
            logger.info("saved debug portal html: %s", debug_html_path)

            result: dict = await page.evaluate(_COURSE_EXTRACT_SCRIPT)

            note = str(result.get("note", ""))
            courses_raw = result.get("courses", []) or []
            courses = [
                Course(
                    name=str(x.get("name", "")).strip(),
                    url=str(x.get("url", "")),
                    course_id=extract_course_id(str(x.get("url", ""))),
                )
                for x in courses_raw
            ]
            courses = [c for c in courses if c.name and c.url]
            logger.info("course extraction: %s (count=%d)", note, len(courses))
            return courses
        finally:
            await context.close()
            await browser.close()


async def eval_courses_on_portal_page(*, page) -> list[Course]:
    result: dict = await page.evaluate(_COURSE_EXTRACT_SCRIPT)
    courses_raw = result.get("courses", []) or []
    courses = [
        Course(
            name=str(x.get("name", "")).strip(),
            url=str(x.get("url", "")),
            course_id=extract_course_id(str(x.get("url", ""))),
        )
        for x in courses_raw
    ]
    return [c for c in courses if c.name and c.url]

