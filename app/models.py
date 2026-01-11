from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class Item:
    source: str
    course: str
    title: str
    url: str
    due: Optional[str] = None
    ts: Optional[str] = None
    raw: dict[str, Any] | None = None

    def fingerprint(self) -> str:
        payload = {
            "source": self.source,
            "course": self.course,
            "title": self.title,
            "url": self.url,
            "due": self.due,
            "ts": self.ts,
        }
        blob = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha1(blob).hexdigest()

