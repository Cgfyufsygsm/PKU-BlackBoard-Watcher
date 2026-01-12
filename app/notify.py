from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BarkMessage:
    title: str
    body: str
    url: str = ""


def simplify_course_name(name: str) -> str:
    """
    Convert portal display names like:
      "25261-...: 信息学中的概率统计(25-26学年第1学期)"
    into:
      "信息学中的概率统计"
    """
    import re

    s = " ".join((name or "").split()).strip()
    if not s:
        return ""

    # Drop leading numeric/code prefix like "25261-...: ".
    if ":" in s:
        prefix, rest = s.split(":", 1)
        if re.search(r"[0-9\-\*]{6,}", prefix):
            s = rest.strip()

    # Drop trailing term suffix like "(25-26学年第1学期)".
    s = re.sub(r"\([^)]*(?:学期|学年)[^)]*\)\s*$", "", s).strip()
    return s


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
    # User preference: do not include clickable URL in pushes (many clients won't open it anyway).
    # Keep the function signature for compatibility, but ignore `url`.
    params = {}

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


def humanize_time(raw: str) -> str:
    """
    Convert internal ISO-8601 times (or common Blackboard display formats) into a more readable CN format:
      2025-10-18T23:59:59+08:00 -> 2025年10月18号 23:59:59
      2025-9-26 -> 2025年9月26号
      2025-11-7 下午11:06 -> 2025年11月7号 23:06:00
    Falls back to original string if parsing fails.
    """
    import re
    from datetime import datetime, timedelta, timezone

    s = " ".join((raw or "").split()).strip()
    if not s or s in {"-", "—"}:
        return ""

    def fmt_dt(dt: datetime) -> str:
        dt8 = dt.astimezone(timezone(timedelta(hours=8))) if dt.tzinfo else dt.replace(tzinfo=timezone(timedelta(hours=8)))
        return f"{dt8.year}年{dt8.month}月{dt8.day}日 {dt8.hour:02}:{dt8.minute:02}:{dt8.second:02}"

    # ISO-8601 datetime
    try:
        if "T" in s:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return fmt_dt(dt)
    except Exception:
        pass

    # CN datetime: "YYYY年M月D日 星期X 下午H:MM(:SS)?" or "YYYY年M月D日 下午H时MM分SS秒"
    m = re.match(
        r"^(?P<y>\d{4})年(?P<m>\d{1,2})月(?P<d>\d{1,2})日"
        r"(?:\s*星期[一二三四五六日天])?"
        r"(?:\s+(?P<ampm>上午|下午|中午|晚上))?"
        r"(?:\s*(?P<h>\d{1,2})(?:时|:)(?P<mi>\d{1,2})(?:分|:)??(?P<s>\d{1,2})?(?:秒)?)?"
        r"(?:\s+(?P<tz>[A-Za-z]{2,5}))?$",
        s,
    )
    if m:
        y, mo, d = int(m.group("y")), int(m.group("m")), int(m.group("d"))
        if not m.group("h"):
            return f"{y}年{mo}月{d}日"
        h, mi = int(m.group("h")), int(m.group("mi"))
        sec = int(m.group("s") or 0)
        ampm = (m.group("ampm") or "").strip()
        if ampm in {"下午", "晚上"} and h < 12:
            h += 12
        elif ampm == "上午" and h == 12:
            h = 0
        elif ampm == "中午" and h < 11:
            h += 12
        return f"{y}年{mo}月{d}日 {h:02}:{mi:02}:{sec:02}"

    # ISO date only
    m = re.match(r"^(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})$", s)
    if m:
        y, mo, d = int(m.group("y")), int(m.group("m")), int(m.group("d"))
        return f"{y}年{mo}月{d}日"

    # Blackboard CN display: "YYYY-M-D 下午H:MM" or "YYYY-M-D 上午H:MM"
    m = re.match(r"^(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})\s+(?P<ampm>上午|下午)?(?P<h>\d{1,2}):(?P<mi>\d{2})$", s)
    if m:
        y, mo, d = int(m.group("y")), int(m.group("m")), int(m.group("d"))
        h, mi = int(m.group("h")), int(m.group("mi"))
        ampm = (m.group("ampm") or "").strip()
        if ampm == "下午" and h < 12:
            h += 12
        if ampm == "上午" and h == 12:
            h = 0
        return f"{y}年{mo}月{d}日 {h:02}:{mi:02}:00"

    # Attempt stamp: "YY-M-D 下午H:MM" (assume 2000+YY)
    m = re.match(r"^(?P<yy>\d{2})-(?P<m>\d{1,2})-(?P<d>\d{1,2})\s+(?P<ampm>上午|下午)?(?P<h>\d{1,2}):(?P<mi>\d{2})$", s)
    if m:
        y = 2000 + int(m.group("yy"))
        mo, d = int(m.group("m")), int(m.group("d"))
        h, mi = int(m.group("h")), int(m.group("mi"))
        ampm = (m.group("ampm") or "").strip()
        if ampm == "下午" and h < 12:
            h += 12
        if ampm == "上午" and h == 12:
            h = 0
        return f"{y}年{mo}月{d}日 {h:02}:{mi:02}:00"

    return s


def build_bark_message(
    *,
    kind: str,
    course_name: str,
    item_title: str,
    url: str = "",
    lines: list[str] | None = None,
) -> BarkMessage:
    display_course = simplify_course_name(course_name) or course_name
    title = f"[{display_course}] {kind}".strip()
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
            lines.append(f"发布时间: {humanize_time(published) or published}")
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
        lines: list[str] = []
        due = raw.get("due_at") or raw.get("due_at_raw") or ""
        if online:
            if due:
                lines.append(f"到期: {humanize_time(due) or due}")
            submitted = raw.get("submitted", None)
            if submitted is True:
                submitted_at = raw.get("submitted_at_raw") or ""
                if submitted_at:
                    lines.append(f"已提交: {humanize_time(submitted_at) or submitted_at}")
                else:
                    lines.append("已提交")
        else:
            lines.append("在线提交: 否")
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
            lines.append(f"到期: {humanize_time(due) or due}")
        if last:
            lines.append(f"评分时间: {humanize_time(last) or last}")
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
                lines.append(f"到期: {humanize_time(new_due) or new_due}")
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
                lines.append(f"到期: {(humanize_time(old_due) or old_due)} -> {(humanize_time(new_due) or new_due)}".strip())
            if new_status and new_status != old_status:
                lines.append(f"状态: {old_status} -> {new_status}".strip())
            return build_bark_message(kind=kind, course_name=course_name, item_title=title, url=url, lines=lines)

        # Other changes (due/points/status/category). Keep it verbose but bounded.
        diffs: list[str] = []
        if old_points != new_points:
            diffs.append(f"满分: {old_points} -> {new_points}".strip())
        if old_due != new_due:
            diffs.append(f"到期: {(humanize_time(old_due) or old_due)} -> {(humanize_time(new_due) or new_due)}".strip())
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

        old_due = s(old_raw.get("due_at") or old_raw.get("due_at_raw") or "")
        new_due = s(new_raw.get("due_at") or new_raw.get("due_at_raw") or "")
        old_points = s(old_raw.get("points_possible_raw") or "")
        new_points = s(new_raw.get("points_possible_raw") or "")
        old_grade = s(old_raw.get("grade_raw") or "")
        new_grade = s(new_raw.get("grade_raw") or "")
        old_submitted = old_raw.get("submitted", None)
        new_submitted = new_raw.get("submitted", None)
        old_submitted_at = s(old_raw.get("submitted_at_raw") or "")
        new_submitted_at = s(new_raw.get("submitted_at_raw") or "")

        diffs: list[str] = []
        if old_online != new_online:
            diffs.append(f"在线提交: {'是' if old_online else '否'} -> {'是' if new_online else '否'}")
        if old_submitted != new_submitted and (old_submitted is not None or new_submitted is not None):
            def fmt_sub(v) -> str:
                if v is True:
                    return "已提交"
                if v is False:
                    return "未提交"
                return "未知"
            diffs.append(f"提交状态: {fmt_sub(old_submitted)} -> {fmt_sub(new_submitted)}")
            if new_submitted is True and new_submitted_at:
                diffs.append(f"提交时间: {humanize_time(new_submitted_at) or new_submitted_at}")
        if old_due != new_due and (old_due or new_due) and (new_online or old_online):
            diffs.append(f"到期: {(humanize_time(old_due) or old_due)} -> {(humanize_time(new_due) or new_due)}".strip())
        if old_points != new_points and (old_points or new_points):
            diffs.append(f"满分: {old_points} -> {new_points}".strip())
        if old_grade != new_grade and (old_grade or new_grade):
            diffs.append(f"成绩: {old_grade} -> {new_grade}".strip())
        if old_url != new_url and (old_url or new_url):
            diffs.append("链接发生变化")

        if diffs:
            return build_bark_message(kind="作业更新", course_name=course_name, item_title=title, url=url, lines=diffs[:6])
        return None

    return None
