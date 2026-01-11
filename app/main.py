from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from app.bb import check_login, fetch_courses_from_portal
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
    args = parser.parse_args(argv)

    root = _project_root()
    config = load_config(root)
    setup_logging(config.log_path)

    logger.info("config loaded")
    init_db(config.db_path)
    logger.info("db init ok: %s", config.db_path)

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
            logger.info("course: %s | %s", c.name, c.url)

    logger.info("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
