from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None  # type: ignore[assignment]

def _load_dotenv_fallback(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return
    import os

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if not key:
            continue
        os.environ.setdefault(key, value)


def _as_bool(value: Optional[str], default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_int(value: Optional[str], default: int) -> int:
    if value is None or value == "":
        return default
    return int(value)


@dataclass(frozen=True)
class Config:
    bb_base_url: str
    bb_login_url: str
    bb_courses_url: str
    bb_state_path: Path

    db_path: Path
    bark_endpoint: str
    poll_limit_per_run: int
    headless: bool
    log_path: Path


def load_config(project_root: Path) -> Config:
    dotenv_path = project_root / ".env"
    if load_dotenv is not None:
        load_dotenv(dotenv_path, override=False)
    else:
        _load_dotenv_fallback(dotenv_path)

    def getenv(name: str, default: str = "") -> str:
        import os

        return os.getenv(name, default)

    bb_state_path = Path(getenv("BB_STATE_PATH", str(project_root / "data" / "storage_state.json")))
    db_path = Path(getenv("DB_PATH", str(project_root / "data" / "state.db")))
    log_path = Path(getenv("LOG_PATH", str(project_root / "logs" / "run.log")))

    return Config(
        bb_base_url=getenv("BB_BASE_URL", ""),
        bb_login_url=getenv("BB_LOGIN_URL", ""),
        bb_courses_url=getenv("BB_COURSES_URL", ""),
        bb_state_path=bb_state_path,
        db_path=db_path,
        bark_endpoint=getenv("BARK_ENDPOINT", ""),
        poll_limit_per_run=_as_int(getenv("POLL_LIMIT_PER_RUN"), 5),
        headless=_as_bool(getenv("HEADLESS"), True),
        log_path=log_path,
    )
