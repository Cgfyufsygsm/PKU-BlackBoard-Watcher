from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.bb import export_storage_state  # noqa: E402
from app.config import load_config  # noqa: E402


def _project_root() -> Path:
    return PROJECT_ROOT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode (not recommended).")
    args = parser.parse_args(argv)

    root = _project_root()
    config = load_config(root)

    asyncio.run(
        export_storage_state(
            login_url=config.bb_login_url,
            state_path=config.bb_state_path,
            headless=args.headless,
        )
    )
    print(f"Saved: {config.bb_state_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
