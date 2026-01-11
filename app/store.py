from __future__ import annotations

import sqlite3
from pathlib import Path


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
              fp TEXT PRIMARY KEY,
              course TEXT,
              source TEXT,
              title TEXT,
              url TEXT,
              due TEXT,
              ts TEXT,
              raw_json TEXT,
              created_at TEXT,
              sent_at TEXT
            )
            """
        )
        conn.commit()

