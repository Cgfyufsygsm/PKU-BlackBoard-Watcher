from __future__ import annotations

from app.bb.announcements import DebugAnnouncementsResult, debug_dump_course_announcements, parse_announcements_html
from app.bb.assignments import (
    DebugAssignmentSamplesResult,
    DebugAssignmentsResult,
    debug_dump_assignment_samples,
    debug_dump_assignments,
    parse_assignments_html,
)
from app.bb.courses import Course, fetch_courses_from_portal
from app.bb.fetch_all import FetchAllResult, fetch_all_items
from app.bb.grades import DebugGradesResult, debug_dump_grades, parse_grades_html
from app.bb.login import LoginCheckResult, check_login
from app.bb.state import export_storage_state
from app.bb.teaching_content import DebugTeachingContentResult, debug_dump_teaching_content, parse_teaching_content_html

__all__ = [
    "Course",
    "DebugAnnouncementsResult",
    "DebugAssignmentSamplesResult",
    "DebugAssignmentsResult",
    "DebugGradesResult",
    "DebugTeachingContentResult",
    "FetchAllResult",
    "LoginCheckResult",
    "check_login",
    "debug_dump_course_announcements",
    "debug_dump_assignment_samples",
    "debug_dump_assignments",
    "debug_dump_grades",
    "debug_dump_teaching_content",
    "export_storage_state",
    "fetch_all_items",
    "fetch_courses_from_portal",
    "parse_announcements_html",
    "parse_assignments_html",
    "parse_grades_html",
    "parse_teaching_content_html",
]
