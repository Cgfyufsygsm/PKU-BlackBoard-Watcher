from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path

from app.bb import (
    check_login,
    debug_dump_course_announcements,
    debug_dump_assignment_samples,
    debug_dump_assignments,
    debug_dump_grades,
    debug_dump_teaching_content,
    fetch_all_items,
    fetch_courses_from_portal,
    parse_announcements_html,
    parse_assignments_html,
    parse_grades_html,
    parse_teaching_content_html,
)
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
    parser.add_argument("--debug-teaching-content", action="store_true", help='Dump HTML for one course "教学内容" page.')
    parser.add_argument("--debug-assignments", action="store_true", help='Dump HTML for one course "课程作业" page.')
    parser.add_argument(
        "--debug-assignment-samples",
        action="store_true",
        help='Dump two assignment detail HTML pages (submitted/unsubmitted samples) for one course.',
    )
    parser.add_argument("--debug-grades", action="store_true", help='Dump HTML for one course "个人成绩" page.')
    parser.add_argument("--fetch-all", action="store_true", help="Fetch all courses and all boards into unified Items.")
    parser.add_argument("--course-query", default="", help="Substring to match the target course in portal list.")
    parser.add_argument("--course-limit", type=int, default=0, help="Limit courses fetched for --fetch-all (0 = no limit).")
    parser.add_argument("--submitted-assignment-query", default="", help="Substring to match the submitted assignment title.")
    parser.add_argument("--unsubmitted-assignment-query", default="", help="Substring to match the unsubmitted assignment title.")
    parser.add_argument("--parse-announcements-html", default="", help="Parse a saved announcements HTML file (offline).")
    parser.add_argument("--parse-teaching-content-html", default="", help='Parse a saved "教学内容" HTML file (offline).')
    parser.add_argument("--parse-assignments-html", default="", help='Parse a saved "课程作业" HTML file (offline).')
    parser.add_argument("--announcements-json", default="", help="Write parsed announcements to a JSON file.")
    parser.add_argument("--teaching-content-json", default="", help='Write parsed "教学内容" items to a JSON file.')
    parser.add_argument("--assignments-json", default="", help='Write parsed "课程作业" items to a JSON file.')
    parser.add_argument("--parse-grades-html", default="", help='Parse a saved "个人成绩" HTML file (offline).')
    parser.add_argument("--grades-json", default="", help='Write parsed "个人成绩" items to a JSON file.')
    parser.add_argument("--items-json", default="", help="Write unified Items to a JSON file (for --fetch-all).")
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
    if args.teaching_content_json and not (args.parse_teaching_content_html or args.debug_teaching_content):
        logger.error("--teaching-content-json must be used with --parse-teaching-content-html or --debug-teaching-content")
        return 2
    if args.assignments_json and not (args.parse_assignments_html or args.debug_assignments):
        logger.error("--assignments-json must be used with --parse-assignments-html or --debug-assignments")
        return 2
    if args.grades_json and not (args.parse_grades_html or args.debug_grades):
        logger.error("--grades-json must be used with --parse-grades-html or --debug-grades")
        return 2
    if args.items_json and not args.fetch_all:
        logger.error("--items-json must be used with --fetch-all")
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

    if args.parse_teaching_content_html:
        html_path = Path(args.parse_teaching_content_html)
        html = html_path.read_text(encoding="utf-8")
        items = parse_teaching_content_html(html=html, base_url=config.bb_base_url)
        logger.info('parsed teaching content from %s: %d', html_path, len(items))
        if args.teaching_content_json:
            out_path = Path(args.teaching_content_json)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            logger.info("wrote teaching content json: %s", out_path)
        for it in items[:10]:
            if it.get("source") == "assignment":
                logger.info(
                    "assignment(in content): online=%s | %s | %s",
                    it.get("is_online_submission", False),
                    it.get("title", ""),
                    it.get("url", ""),
                )
            else:
                logger.info(
                    "teaching_content: %s | attachments=%s | %s",
                    it.get("title", ""),
                    it.get("has_attachments", False),
                    it.get("url", ""),
                )
        logger.info("done")
        return 0

    if args.parse_assignments_html:
        html_path = Path(args.parse_assignments_html)
        html = html_path.read_text(encoding="utf-8")
        items = parse_assignments_html(html=html, base_url=config.bb_base_url)
        logger.info('parsed assignments from %s: %d', html_path, len(items))
        if args.assignments_json:
            out_path = Path(args.assignments_json)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            logger.info("wrote assignments json: %s", out_path)
        for it in items[:15]:
            logger.info(
                "assignment: online=%s | %s | %s",
                it.get("is_online_submission", False),
                it.get("title", ""),
                it.get("url", ""),
            )
        logger.info("done")
        return 0

    if args.parse_grades_html:
        html_path = Path(args.parse_grades_html)
        html = html_path.read_text(encoding="utf-8")
        items = parse_grades_html(html=html, base_url=config.bb_base_url)
        logger.info('parsed grades from %s: %d', html_path, len(items))
        if args.grades_json:
            out_path = Path(args.grades_json)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            logger.info("wrote grades json: %s", out_path)
        for it in items[:15]:
            logger.info(
                "grade_item: %s | cat=%s | last=%s | grade=%s/%s",
                it.get("title", ""),
                it.get("category", ""),
                it.get("lastactivity", "") or it.get("lastactivity_display", ""),
                it.get("grade_raw", ""),
                it.get("points_possible_raw", ""),
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

    if args.fetch_all:
        result = asyncio.run(
            fetch_all_items(
                state_path=config.bb_state_path,
                portal_url=config.bb_courses_url or config.bb_base_url,
                headless=config.headless,
                course_limit=args.course_limit,
            )
        )
        logger.info("fetch-all courses: %d", len(result.courses))
        logger.info("fetch-all items: %d", len(result.items))
        if result.errors:
            hard = [e for e in result.errors if e.get("kind") != "missing_menu"]
            skipped = [e for e in result.errors if e.get("kind") == "missing_menu"]
            if skipped:
                logger.info("fetch-all skipped boards (menu missing): %d", len(skipped))
            if hard:
                logger.warning("fetch-all errors: %d", len(hard))
                for e in hard[:20]:
                    logger.warning(
                        "fetch-all error: course=%s (%s) board=%s err=%s",
                        e.get("course_name", ""),
                        e.get("course_id", ""),
                        e.get("board", ""),
                        e.get("error", ""),
                    )
        if args.items_json:
            out_path = Path(args.items_json)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(
                json.dumps([it.to_dict() for it in result.items], ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            logger.info("wrote items json: %s", out_path)
        logger.info("done")
        return 0

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

    if args.debug_teaching_content:
        if not args.course_query:
            logger.error("--course-query is required for --debug-teaching-content")
            return 2
        result = asyncio.run(
            debug_dump_teaching_content(
                state_path=config.bb_state_path,
                portal_url=config.bb_courses_url or config.bb_base_url,
                course_query=args.course_query,
                headless=config.headless,
                portal_html_path=root / "data" / "debug_courses.html",
                course_entry_html_path=root / "data" / "debug_course_entry.html",
                teaching_content_html_path=root / "data" / "debug_teaching_content.html",
            )
        )
        logger.info("debug teaching content ok: %s (course_id=%s)", result.course.name, result.course.course_id)
        logger.info("course_entry_url: %s", result.course_entry_url)
        logger.info("teaching_content_url: %s", result.teaching_content_url)
        logger.info("teaching content items found: %d", len(result.items))
        if args.teaching_content_json:
            out_path = Path(args.teaching_content_json)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(result.items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            logger.info("wrote teaching content json: %s", out_path)
        for it in result.items[:10]:
            if it.get("source") == "assignment":
                logger.info(
                    "assignment(in content): online=%s | %s | %s",
                    it.get("is_online_submission", False),
                    it.get("title", ""),
                    it.get("url", ""),
                )
            else:
                logger.info(
                    "teaching_content: %s | attachments=%s | %s",
                    it.get("title", ""),
                    it.get("has_attachments", False),
                    it.get("url", ""),
                )

    if args.debug_assignments:
        if not args.course_query:
            logger.error("--course-query is required for --debug-assignments")
            return 2
        result = asyncio.run(
            debug_dump_assignments(
                state_path=config.bb_state_path,
                portal_url=config.bb_courses_url or config.bb_base_url,
                course_query=args.course_query,
                headless=config.headless,
                portal_html_path=root / "data" / "debug_courses.html",
                course_entry_html_path=root / "data" / "debug_course_entry.html",
                assignments_html_path=root / "data" / "debug_assignments.html",
            )
        )
        logger.info("debug assignments ok: %s (course_id=%s)", result.course.name, result.course.course_id)
        logger.info("course_entry_url: %s", result.course_entry_url)
        logger.info("assignments_url: %s", result.assignments_url)
        logger.info("assignments found: %d", len(result.items))
        if args.assignments_json:
            out_path = Path(args.assignments_json)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(result.items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            logger.info("wrote assignments json: %s", out_path)
        for it in result.items[:15]:
            logger.info(
                "assignment: online=%s | %s | %s",
                it.get("is_online_submission", False),
                it.get("title", ""),
                it.get("url", ""),
            )

    if args.debug_assignment_samples:
        if not args.course_query:
            logger.error("--course-query is required for --debug-assignment-samples")
            return 2
        if not args.submitted_assignment_query or not args.unsubmitted_assignment_query:
            logger.error("--submitted-assignment-query and --unsubmitted-assignment-query are required for --debug-assignment-samples")
            return 2
        result = asyncio.run(
            debug_dump_assignment_samples(
                state_path=config.bb_state_path,
                portal_url=config.bb_courses_url or config.bb_base_url,
                course_query=args.course_query,
                submitted_assignment_query=args.submitted_assignment_query,
                unsubmitted_assignment_query=args.unsubmitted_assignment_query,
                headless=config.headless,
                assignments_html_path=root / "data" / "debug_assignments.html",
                submitted_html_path=root / "data" / "debug_assignment_submitted.html",
                submitted_new_attempt_html_path=root / "data" / "debug_assignment_submitted_new_attempt.html",
                unsubmitted_html_path=root / "data" / "debug_assignment_unsubmitted.html",
            )
        )
        logger.info("assignment samples ok: %s (course_id=%s)", result.course.name, result.course.course_id)
        logger.info("assignments_url: %s", result.assignments_url)
        logger.info("submitted sample: %s | %s | %s", result.submitted_title, result.submitted_url, result.submitted_html_path)
        logger.info(
            "submitted info: due=%s points=%s grade=%s",
            result.submitted_info.get("due_at_raw", ""),
            result.submitted_info.get("points_possible_raw", ""),
            result.submitted_info.get("grade_raw", ""),
        )
        if result.submitted_new_attempt_url:
            logger.info("submitted new-attempt url: %s", result.submitted_new_attempt_url)
            logger.info(
                "submitted new-attempt info: due=%s points=%s grade=%s (html=%s)",
                result.submitted_new_attempt_info.get("due_at_raw", ""),
                result.submitted_new_attempt_info.get("points_possible_raw", ""),
                result.submitted_new_attempt_info.get("grade_raw", ""),
                result.submitted_new_attempt_html_path,
            )
        logger.info("unsubmitted sample: %s | %s | %s", result.unsubmitted_title, result.unsubmitted_url, result.unsubmitted_html_path)
        logger.info(
            "unsubmitted info: due=%s points=%s",
            result.unsubmitted_info.get("due_at_raw", ""),
            result.unsubmitted_info.get("points_possible_raw", ""),
        )

    if args.debug_grades:
        if not args.course_query:
            logger.error("--course-query is required for --debug-grades")
            return 2
        result = asyncio.run(
            debug_dump_grades(
                state_path=config.bb_state_path,
                portal_url=config.bb_courses_url or config.bb_base_url,
                course_query=args.course_query,
                headless=config.headless,
                portal_html_path=root / "data" / "debug_courses.html",
                course_entry_html_path=root / "data" / "debug_course_entry.html",
                grades_html_path=root / "data" / "debug_grades.html",
            )
        )
        logger.info("debug grades ok: %s (course_id=%s)", result.course.name, result.course.course_id)
        logger.info("course_entry_url: %s", result.course_entry_url)
        logger.info("grades_url: %s", result.grades_url)
        logger.info("grade items found: %d", len(result.grades))
        if args.grades_json:
            out_path = Path(args.grades_json)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(result.grades, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            logger.info("wrote grades json: %s", out_path)
        for it in result.grades[:15]:
            logger.info(
                "grade_item: %s | cat=%s | due=%s | last=%s | grade=%s/%s",
                it.get("title", ""),
                it.get("category", ""),
                it.get("duedate_display", "") or it.get("duedate", ""),
                it.get("lastactivity", "") or it.get("lastactivity_display", ""),
                it.get("grade_raw", ""),
                it.get("points_possible_raw", ""),
            )

    logger.info("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
