from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path

from app.bb import check_login, debug_dump_course_announcements, fetch_courses_from_portal, parse_announcements_html
from app.config import load_config
from app.logging_utils import setup_logging
from app.store import init_db


logger = logging.getLogger(__name__)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pku-bb-watcher")
    parser.add_argument("--check-login", action="store_true", help="Open a page using storage_state and log title/url.")
    parser.add_argument("--list-courses", action="store_true", help="Dump portal HTML and extract student courses.")
    parser.add_argument("--debug-announcements", action="store_true", help="Dump HTML for one course announcements page.")
    parser.add_argument("--course-query", default="", help="Substring to match the target course in portal list.")
    parser.add_argument("--parse-announcements-html", default="", help="Parse a saved announcements HTML file (offline).")
    parser.add_argument("--announcements-json", default="", help="Write parsed announcements to a JSON file.")
    args = parser.parse_args(argv)

    root = _project_root()
    config = load_config(root)
    setup_logging(config.log_path)

    logger.info("config loaded")
    init_db(config.db_path)
    logger.info("db init ok: %s", config.db_path)

    if args.announcements_json and not (args.parse_announcements_html or args.debug_announcements):
        logger.error("--announcements-json must be used with --parse-announcements-html or --debug-announcements")
        return 2

    if args.parse_announcements_html:
        html_path = Path(args.parse_announcements_html)
        html = html_path.read_text(encoding="utf-8")
        announcements = parse_announcements_html(html=html, base_url=config.bb_base_url)
        logger.info("parsed announcements from %s: %d", html_path, len(announcements))
        if args.announcements_json:
            out_path = Path(args.announcements_json)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(announcements, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            logger.info("wrote announcements json: %s", out_path)
        for a in announcements[:10]:
            logger.info(
                "announcement: %s (%s) | %s | %s",
                a.get("published_at", ""),
                a.get("published_at_raw", ""),
                a.get("title", ""),
                a.get("url", ""),
            )
        logger.info("done")
        return 0

    if args.check_login:
        result = asyncio.run(
            check_login(
                state_path=config.bb_state_path,
                check_url=config.bb_courses_url or config.bb_base_url,
                headless=config.headless,
            )
        )
        if result.ok:
            logger.info("login ok: %s (%s)", result.title, result.final_url)
        else:
            logger.warning("login not ok: %s", result.note or "unknown")
            return 2

    if args.list_courses:
        debug_html_path = root / "data" / "debug_courses.html"
        courses = asyncio.run(
            fetch_courses_from_portal(
                state_path=config.bb_state_path,
                portal_url=config.bb_courses_url or config.bb_base_url,
                headless=config.headless,
                debug_html_path=debug_html_path,
            )
        )
        logger.info("courses found: %d", len(courses))
        for c in courses[:30]:
            extra = f" (course_id={c.course_id})" if getattr(c, "course_id", "") else ""
            logger.info("course: %s%s | %s", c.name, extra, c.url)

    if args.debug_announcements:
        if not args.course_query:
            logger.error("--course-query is required for --debug-announcements")
            return 2
        result = asyncio.run(
            debug_dump_course_announcements(
                state_path=config.bb_state_path,
                portal_url=config.bb_courses_url or config.bb_base_url,
                course_query=args.course_query,
                headless=config.headless,
                portal_html_path=root / "data" / "debug_courses.html",
                course_entry_html_path=root / "data" / "debug_course_entry.html",
                announcements_html_path=root / "data" / "debug_announcements.html",
            )
        )
        logger.info("debug announcements ok: %s (course_id=%s)", result.course.name, result.course.course_id)
        logger.info("course_entry_url: %s", result.course_entry_url)
        logger.info("announcements_url: %s", result.announcements_url)
        logger.info("announcements found: %d", len(result.announcements))
        if args.announcements_json:
            out_path = Path(args.announcements_json)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(result.announcements, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            logger.info("wrote announcements json: %s", out_path)
        for a in result.announcements[:10]:
            logger.info(
                "announcement: %s (%s) | %s | %s",
                a.get("published_at", ""),
                a.get("published_at_raw", ""),
                a.get("title", ""),
                a.get("url", ""),
            )

    logger.info("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
