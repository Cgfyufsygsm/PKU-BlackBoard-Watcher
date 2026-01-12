from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class Item:
    source: str
    course_id: str
    course_name: str
    title: str
    url: str
    due: Optional[str] = None
    ts: Optional[str] = None
    external_id: Optional[str] = None
    raw: dict[str, Any] | None = None

    def identity_fp(self) -> str:
        """
        Stable identity key (one row per logical item).

        Priority:
        - course_id (avoid cross-semester collisions on same course name)
        - external_id (row/content/announcement ids when available)
        - url (stable detail link or history link) as fallback
        - title as last resort
        """
        payload: dict[str, str] = {
            "source": (self.source or "").strip(),
            "course_id": (self.course_id or "").strip(),
        }
        external_id = (self.external_id or "").strip()
        url = (self.url or "").strip()
        title = (self.title or "").strip()

        if external_id:
            payload["external_id"] = external_id
        elif url:
            payload["url"] = url
        else:
            payload["title"] = title

        blob = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha1(blob).hexdigest()

    def state_fp(self) -> str:
        """
        Hash of the current item state (used to detect updates on the same identity).
        """
        raw = self.raw or {}
        source = (self.source or "").strip()

        state: dict[str, Any] = {
            "id": self.identity_fp(),
            "title": (self.title or "").strip(),
            "url": (self.url or "").strip(),
            "due": (self.due or "").strip(),
            "ts": (self.ts or "").strip(),
        }

        if source == "announcement":
            state["published_at"] = raw.get("published_at", "")
            state["published_at_raw"] = raw.get("published_at_raw", "")
            state["author"] = raw.get("author", "")
            state["content"] = raw.get("content", "")
        elif source == "teaching_content":
            state["has_attachments"] = bool(raw.get("has_attachments", False))
            state["content"] = raw.get("content", "")
        elif source == "assignment":
            state["is_online_submission"] = bool(raw.get("is_online_submission", False))
            state["submitted"] = raw.get("submitted", None)
            state["submitted_at_raw"] = raw.get("submitted_at_raw", "")
            state["grade_raw"] = raw.get("grade_raw", "")
            state["points_possible_raw"] = raw.get("points_possible_raw", "")
        elif source == "grade_item":
            state["category"] = raw.get("category", "")
            state["status"] = raw.get("status", "")
            state["grade_raw"] = raw.get("grade_raw", "")
            state["points_possible_raw"] = raw.get("points_possible_raw", "")

        blob = json.dumps(state, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha1(blob).hexdigest()

    def fingerprint(self) -> str:
        # Backward-compatible alias: fp is the identity key.
        return self.identity_fp()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "course_id": self.course_id,
            "course_name": self.course_name,
            "title": self.title,
            "url": self.url,
            "due": self.due or "",
            "ts": self.ts or "",
            "external_id": self.external_id or "",
            "fp": self.identity_fp(),
            "state_fp": self.state_fp(),
            "raw": self.raw or {},
        }
