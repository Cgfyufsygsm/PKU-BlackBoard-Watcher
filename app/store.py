from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.models import Item


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
              fp TEXT PRIMARY KEY,
              course_id TEXT,
              course_name TEXT,
              source TEXT,
              external_id TEXT,
              state_fp TEXT,
              sent_state_fp TEXT,
              title TEXT,
              url TEXT,
              due TEXT,
              ts TEXT,
              raw_json TEXT,
              created_at TEXT,
              updated_at TEXT,
              sent_at TEXT
            )
            """
        )
        _migrate_items_table(conn)
        conn.commit()


def get_notification_counts(db_path: Path) -> tuple[int, int]:
    """
    Returns (total_rows, notified_rows).
    notified_rows are rows with non-empty sent_state_fp.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        _migrate_items_table(conn)
        total = int(conn.execute("SELECT COUNT(1) FROM items").fetchone()[0])
        notified = int(conn.execute("SELECT COUNT(1) FROM items WHERE sent_state_fp IS NOT NULL AND sent_state_fp!=''").fetchone()[0])
        return total, notified


def _migrate_items_table(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(items)").fetchall()}
    # Old schema used `course` only; keep it if present but write to course_name.
    if "course" in cols and "course_name" not in cols:
        conn.execute("ALTER TABLE items ADD COLUMN course_name TEXT")
        conn.execute("UPDATE items SET course_name=course WHERE (course_name IS NULL OR course_name='') AND course IS NOT NULL AND course!=''")
    for col in ["course_id", "course_name", "external_id", "state_fp", "sent_state_fp", "updated_at"]:
        if col not in cols:
            conn.execute(f"ALTER TABLE items ADD COLUMN {col} TEXT")
    # Backfill: if previously sent but no sent_state_fp recorded, treat current state_fp as last notified.
    cols = {row[1] for row in conn.execute("PRAGMA table_info(items)").fetchall()}
    if "sent_state_fp" in cols and "state_fp" in cols and "sent_at" in cols:
        conn.execute(
            "UPDATE items SET sent_state_fp=state_fp "
            "WHERE (sent_state_fp IS NULL OR sent_state_fp='') AND (sent_at IS NOT NULL AND sent_at!='') AND (state_fp IS NOT NULL AND state_fp!='')"
        )


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def bulk_filter_new(db_path: Path, items: list[Item]) -> list[Item]:
    """
    Returns items whose fp is not present in DB.
    (This is the pure de-dup filter; Step E push loop will additionally
    decide whether to mark sent or skip.)
    """
    if not items:
        return []
    fps = [it.identity_fp() for it in items]
    existing: set[str] = set()
    with sqlite3.connect(db_path) as conn:
        _migrate_items_table(conn)
        # SQLite has a parameter limit; chunk to stay safe.
        chunk_size = 900
        for i in range(0, len(fps), chunk_size):
            chunk = fps[i : i + chunk_size]
            q = ",".join("?" for _ in chunk)
            rows = conn.execute(f"SELECT fp FROM items WHERE fp IN ({q})", chunk).fetchall()
            existing.update(r[0] for r in rows)
    return [it for it in items if it.identity_fp() not in existing]


def upsert_seen(db_path: Path, items: list[Item]) -> int:
    """
    Insert items into DB (idempotent). Returns number of new rows inserted.
    """
    if not items:
        return 0
    now = _now_iso()
    rows = []
    for it in items:
        fp = it.identity_fp()
        raw_json = json.dumps(it.raw or {}, ensure_ascii=False, sort_keys=True)
        state_fp = it.state_fp()
        rows.append(
            (
                fp,
                it.course_id,
                it.course_name,
                it.source,
                it.external_id or "",
                state_fp,
                it.title,
                it.url,
                it.due or "",
                it.ts or "",
                raw_json,
                now,
                now,
            )
        )

    with sqlite3.connect(db_path) as conn:
        _migrate_items_table(conn)
        cur = conn.executemany(
            """
            INSERT INTO items (
              fp, course_id, course_name, source, external_id, state_fp,
              title, url, due, ts, raw_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(fp) DO UPDATE SET
              course_id=excluded.course_id,
              course_name=excluded.course_name,
              source=excluded.source,
              external_id=excluded.external_id,
              state_fp=excluded.state_fp,
              title=excluded.title,
              url=excluded.url,
              due=excluded.due,
              ts=excluded.ts,
              raw_json=excluded.raw_json,
              updated_at=excluded.updated_at
            """,
            rows,
        )
        conn.commit()
        return cur.rowcount or 0


def bulk_classify(db_path: Path, items: list[Item]) -> tuple[list[Item], list[Item], list[Item]]:
    """
    Returns (new, updated, unchanged), where:
    - new: identity_fp not in DB
    - updated: identity exists but state_fp differs
    - unchanged: identity exists and state_fp same
    """
    if not items:
        return ([], [], [])

    by_fp = {it.identity_fp(): it for it in items}
    fps = list(by_fp.keys())

    existing_state: dict[str, str] = {}
    with sqlite3.connect(db_path) as conn:
        _migrate_items_table(conn)
        chunk_size = 900
        for i in range(0, len(fps), chunk_size):
            chunk = fps[i : i + chunk_size]
            q = ",".join("?" for _ in chunk)
            rows = conn.execute(f"SELECT fp, COALESCE(state_fp,'') FROM items WHERE fp IN ({q})", chunk).fetchall()
            for fp, state_fp in rows:
                existing_state[str(fp)] = str(state_fp or "")

    new_items: list[Item] = []
    updated_items: list[Item] = []
    unchanged_items: list[Item] = []
    for fp, it in by_fp.items():
        if fp not in existing_state:
            new_items.append(it)
            continue
        if existing_state.get(fp, "") != it.state_fp():
            updated_items.append(it)
        else:
            unchanged_items.append(it)
    return (new_items, updated_items, unchanged_items)


def mark_sent(db_path: Path, fps: list[str]) -> int:
    if not fps:
        return 0
    now = _now_iso()
    with sqlite3.connect(db_path) as conn:
        _migrate_items_table(conn)
        cur = conn.executemany("UPDATE items SET sent_at=? WHERE fp=? AND (sent_at IS NULL OR sent_at='')", [(now, fp) for fp in fps])
        conn.commit()
        return cur.rowcount or 0


def fetch_records(db_path: Path, fps: list[str]) -> dict[str, dict]:
    """
    Fetch existing DB records for the given identity fps.
    """
    if not fps:
        return {}
    out: dict[str, dict] = {}
    with sqlite3.connect(db_path) as conn:
        _migrate_items_table(conn)
        chunk_size = 900
        for i in range(0, len(fps), chunk_size):
            chunk = fps[i : i + chunk_size]
            q = ",".join("?" for _ in chunk)
            rows = conn.execute(
                f"SELECT fp, COALESCE(state_fp,''), COALESCE(sent_state_fp,''), COALESCE(raw_json,''), COALESCE(sent_at,'') "
                f"FROM items WHERE fp IN ({q})",
                chunk,
            ).fetchall()
            for fp, state_fp, sent_state_fp, raw_json, sent_at in rows:
                try:
                    raw = json.loads(raw_json) if raw_json else {}
                except Exception:
                    raw = {}
                out[str(fp)] = {
                    "state_fp": str(state_fp or ""),
                    "sent_state_fp": str(sent_state_fp or ""),
                    "raw": raw,
                    "sent_at": str(sent_at or ""),
                }
    return out


def mark_notified(db_path: Path, pairs: list[tuple[str, str]]) -> int:
    """
    Mark (fp, state_fp) as notified; sets sent_at and sent_state_fp.
    """
    if not pairs:
        return 0
    now = _now_iso()
    with sqlite3.connect(db_path) as conn:
        _migrate_items_table(conn)
        cur = conn.executemany(
            "UPDATE items SET sent_at=?, sent_state_fp=? WHERE fp=?",
            [(now, state_fp, fp) for fp, state_fp in pairs],
        )
        conn.commit()
        return cur.rowcount or 0


def ack_state(db_path: Path, pairs: list[tuple[str, str]]) -> int:
    """
    Acknowledge (fp, state_fp) without pushing (no sent_at update).
    Useful when we intentionally ignore updates for certain sources.
    """
    if not pairs:
        return 0
    with sqlite3.connect(db_path) as conn:
        _migrate_items_table(conn)
        cur = conn.executemany(
            "UPDATE items SET sent_state_fp=? WHERE fp=?",
            [(state_fp, fp) for fp, state_fp in pairs],
        )
        conn.commit()
        return cur.rowcount or 0
