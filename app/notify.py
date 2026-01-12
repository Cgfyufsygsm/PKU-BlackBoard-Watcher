from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BarkMessage:
    title: str
    body: str
    url: str = ""


def send_bark(*, endpoint: str, title: str, body: str, url: str = "", timeout_s: int = 10) -> None:
    """
    Send a Bark push.

    `endpoint` should look like: https://api.day.app/<token>
    """
    endpoint = (endpoint or "").strip()
    if not endpoint:
        raise ValueError("BARK_ENDPOINT is empty.")

    import requests
    from urllib.parse import quote
    from urllib.parse import urlparse

    def normalize_endpoint(ep: str) -> str:
        ep = (ep or "").strip().rstrip("/")
        if not ep:
            return ""
        # Accept token-only form: "<token>"
        if "://" not in ep:
            if "/" not in ep:
                return f"https://api.day.app/{ep}"
            # Accept host/path without scheme: "api.day.app/<token>"
            return f"https://{ep}"
        return ep

    endpoint = normalize_endpoint(endpoint)
    parsed = urlparse(endpoint)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("Invalid BARK_ENDPOINT; use https://api.day.app/<token> or just <token>.")

    # Bark uses path segments; encode them safely.
    push_url = endpoint.rstrip("/") + "/" + quote(title, safe="") + "/" + quote(body, safe="")
    params = {}
    if url:
        params["url"] = url

    try:
        resp = requests.get(push_url, params=params, timeout=timeout_s)
    except Exception:
        # Avoid leaking token in exception messages.
        raise RuntimeError("bark request failed") from None
    if resp.status_code >= 400:
        raise RuntimeError(f"bark http {resp.status_code}")


def _excerpt(text: str, limit: int = 160) -> str:
    s = " ".join((text or "").split()).strip()
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"


def build_bark_message(
    *,
    kind: str,
    course_name: str,
    item_title: str,
    url: str = "",
    lines: list[str] | None = None,
) -> BarkMessage:
    title = f"[{course_name}] {kind}".strip()
    body_lines = [item_title.strip()] if item_title else []
    body_lines.extend([ln for ln in (lines or []) if ln])
    body = "\n".join(body_lines).strip()
    return BarkMessage(title=title, body=body, url=url or "")


def message_for_new_item(item: dict) -> BarkMessage | None:
    source = (item.get("source") or "").strip()
    course_name = (item.get("course_name") or "").strip()
    title = (item.get("title") or "").strip()
    url = (item.get("url") or "").strip()
    raw = item.get("raw") or {}

    if source == "announcement":
        published = raw.get("published_at") or raw.get("published_at_raw") or ""
        author = raw.get("author", "") or ""
        content = _excerpt(raw.get("content", "") or "", 180)
        lines = []
        if published:
            lines.append(f"发布时间: {published}")
        if author:
            lines.append(f"发帖者: {author}")
        if content:
            lines.append(f"内容: {content}")
        return build_bark_message(kind="新通知", course_name=course_name, item_title=title, url=url, lines=lines)

    if source == "teaching_content":
        has_att = bool(raw.get("has_attachments", False))
        content = _excerpt(raw.get("content", "") or "", 180)
        lines = [f"附件: {'有' if has_att else '无'}"]
        if content:
            lines.append(f"内容: {content}")
        return build_bark_message(kind="新教学内容", course_name=course_name, item_title=title, url=url, lines=lines)

    if source == "assignment":
        online = bool(raw.get("is_online_submission", False))
        lines = [f"在线提交: {'是' if online else '否'}"]
        due = raw.get("due_at") or raw.get("due_at_raw") or ""
        if due:
            lines.append(f"到期: {due}")
        return build_bark_message(kind="新作业", course_name=course_name, item_title=title, url=url, lines=lines)

    if source == "grade_item":
        cat = raw.get("category", "") or ""
        grade_raw = (raw.get("grade_raw") or "").strip()
        points_raw = (raw.get("points_possible_raw") or "").strip()
        due = raw.get("duedate_display") or raw.get("duedate") or ""
        last = raw.get("lastactivity") or raw.get("lastactivity_display") or ""
        lines = []
        if cat:
            lines.append(f"类别: {cat}")
        if grade_raw or points_raw:
            lines.append(f"成绩: {grade_raw}/{points_raw}".rstrip("/"))
        if due:
            lines.append(f"到期: {due}")
        if last:
            lines.append(f"时间: {last}")
        return build_bark_message(kind="新成绩项", course_name=course_name, item_title=title, url=url, lines=lines)

    return None


def message_for_updated_item(*, new_item: dict, old_raw: dict) -> BarkMessage | None:
    source = (new_item.get("source") or "").strip()
    course_name = (new_item.get("course_name") or "").strip()
    title = (new_item.get("title") or "").strip()
    url = (new_item.get("url") or "").strip()
    new_raw = new_item.get("raw") or {}

    def s(v) -> str:
        return " ".join(str(v or "").split()).strip()

    if source == "grade_item":
        cat = s(new_raw.get("category", ""))
        new_grade = s(new_raw.get("grade_raw", ""))
        old_grade = s(old_raw.get("grade_raw", ""))
        new_points = s(new_raw.get("points_possible_raw", ""))
        old_points = s(old_raw.get("points_possible_raw", ""))
        new_due = s(new_raw.get("duedate_display") or new_raw.get("duedate") or "")
        old_due = s(old_raw.get("duedate_display") or old_raw.get("duedate") or "")
        new_status = s(new_raw.get("status", ""))
        old_status = s(old_raw.get("status", ""))

        def is_missing_grade(g: str) -> bool:
            return not g or g in {"-", "—"}

        # Category-aware naming: assignments vs general grade items.
        is_assignment_grade = (cat == "作业") or (s(old_raw.get("category", "")) == "作业")

        if is_missing_grade(old_grade) and not is_missing_grade(new_grade):
            kind = "作业出分" if is_assignment_grade else "成绩出分"
            lines = []
            if cat:
                lines.append(f"类别: {cat}")
            lines.append(f"成绩: {new_grade}/{new_points}".rstrip("/"))
            if new_due:
                lines.append(f"到期: {new_due}")
            if new_status:
                lines.append(f"状态: {new_status}")
            return build_bark_message(kind=kind, course_name=course_name, item_title=title, url=url, lines=lines)

        if old_grade != new_grade:
            kind = "作业成绩变动" if is_assignment_grade else "成绩变动"
            lines = []
            if cat:
                lines.append(f"类别: {cat}")
            lines.append(f"原成绩: {old_grade}/{old_points}".rstrip("/"))
            lines.append(f"新成绩: {new_grade}/{new_points}".rstrip("/"))
            if new_due and new_due != old_due:
                lines.append(f"到期: {old_due} -> {new_due}".strip())
            if new_status and new_status != old_status:
                lines.append(f"状态: {old_status} -> {new_status}".strip())
            return build_bark_message(kind=kind, course_name=course_name, item_title=title, url=url, lines=lines)

        # Other changes (due/points/status/category). Keep it verbose but bounded.
        diffs: list[str] = []
        if old_points != new_points:
            diffs.append(f"满分: {old_points} -> {new_points}".strip())
        if old_due != new_due:
            diffs.append(f"到期: {old_due} -> {new_due}".strip())
        if old_status != new_status:
            diffs.append(f"状态: {old_status} -> {new_status}".strip())
        old_cat = s(old_raw.get("category", ""))
        if old_cat != cat:
            diffs.append(f"类别: {old_cat} -> {cat}".strip())
        if diffs:
            kind = "成绩项更新"
            return build_bark_message(kind=kind, course_name=course_name, item_title=title, url=url, lines=diffs[:6])
        return None

    if source == "assignment":
        old_url = s(old_raw.get("url", "")) or s(old_raw.get("submission_url", ""))
        new_url = s(new_raw.get("url", "")) or s(new_raw.get("submission_url", ""))
        old_online = bool(old_raw.get("is_online_submission", False))
        new_online = bool(new_raw.get("is_online_submission", False))
        diffs = []
        if old_online != new_online:
            diffs.append(f"在线提交: {'是' if old_online else '否'} -> {'是' if new_online else '否'}")
        if old_url != new_url and (old_url or new_url):
            diffs.append("链接发生变化")
        if diffs:
            return build_bark_message(kind="作业条目更新", course_name=course_name, item_title=title, url=url, lines=diffs)
        return None

    return None
