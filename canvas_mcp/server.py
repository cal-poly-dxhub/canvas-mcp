# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Canvas LMS MCP Server — local stdio mode.

Run with: canvas-mcp
Or:       python -m src.server

Requires CANVAS_API_TOKEN and CANVAS_BASE_URL environment variables.
"""

from __future__ import annotations

import functools
import json
import os
import sys
from typing import Any, Callable, List, Optional

import requests
from mcp.server.fastmcp import FastMCP

from .canvas_client import (
    canvas_token_var,
    canvas_base_url_var,
    list_courses,
    list_assignments,
    get_upcoming_assignments,
    get_submission_status,
    get_my_grades,
    get_todo_items,
    create_canvas_event,
    search_course_files,
    create_module,
    add_module_item,
    create_assignment,
    post_announcement,
    create_page,
    get_grade_summary,
)


def _safe_tool(fn: Callable[..., str]) -> Callable[..., str]:
    """Wrap a tool so Canvas/network errors return JSON instead of crashing."""
    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> str:
        try:
            return fn(*args, **kwargs)
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            reason = exc.response.reason if exc.response is not None else str(exc)
            return json.dumps({"error": f"Canvas API error: {status} {reason}"})
        except Exception as exc:
            return json.dumps({"error": str(exc)})
    return wrapper


mcp = FastMCP("canvas-mcp-server")


# ---------------------------------------------------------------------------
# Student tools
# ---------------------------------------------------------------------------

@mcp.tool()
@_safe_tool
def list_upcoming_assignments(days_ahead: int = 14) -> str:
    """List upcoming Canvas assignments for the next N days across all courses.

    Args:
        days_ahead: How many days ahead to look (1-60). Defaults to 14.
    """
    return get_upcoming_assignments(days_ahead)


@mcp.tool()
@_safe_tool
def list_course_assignments(course_id: int) -> str:
    """List all assignments in a course with their IDs, names, due dates, and points.

    Args:
        course_id: The Canvas course ID.
    """
    return list_assignments(course_id)


@mcp.tool()
@_safe_tool
def check_submission_status(course_id: int, assignment_id: int) -> str:
    """Check whether the current user has submitted a specific assignment, and if it's been graded.

    Args:
        course_id: The Canvas course ID.
        assignment_id: The Canvas assignment ID.
    """
    return get_submission_status(course_id, assignment_id)


@mcp.tool()
@_safe_tool
def view_my_grades(course_id: int) -> str:
    """Get the current user's grades for all assignments in a course.

    Args:
        course_id: The Canvas course ID.
    """
    return get_my_grades(course_id)


@mcp.tool()
@_safe_tool
def view_todo_list() -> str:
    """Get the current user's Canvas TODO list — upcoming items that need attention."""
    return get_todo_items()


@mcp.tool()
@_safe_tool
def schedule_canvas_event(title: str, start_at: str, end_at: str) -> str:
    """Create a calendar event on the user's Canvas calendar.

    Args:
        title: Event title.
        start_at: Start time in ISO 8601 with timezone (e.g. 2025-10-12T15:00:00-07:00).
        end_at: End time in ISO 8601 with timezone (e.g. 2025-10-12T17:00:00-07:00).
    """
    return create_canvas_event(title, start_at, end_at)


# ---------------------------------------------------------------------------
# Instructor tools
# ---------------------------------------------------------------------------

@mcp.tool()
@_safe_tool
def get_my_courses() -> str:
    """List all active courses for the current user."""
    return list_courses()


@mcp.tool()
@_safe_tool
def find_course_files(course_id: int, search_term: str = "") -> str:
    """Search or list files in a course.

    Args:
        course_id: The Canvas course ID.
        search_term: Optional keyword to filter files by name.
    """
    return search_course_files(course_id, search_term)


@mcp.tool()
@_safe_tool
def create_course_module(course_id: int, name: str, position: Optional[int] = None) -> str:
    """Create a new module in a course.

    Args:
        course_id: The Canvas course ID.
        name: Module name.
        position: Optional position/order in the modules list.
    """
    return create_module(course_id, name, position)


@mcp.tool()
@_safe_tool
def add_item_to_module(course_id: int, module_id: int, item_type: str, title: str, content_id: Optional[int] = None, external_url: Optional[str] = None, page_url: Optional[str] = None) -> str:
    """Add an item to an existing module.

    Args:
        course_id: The Canvas course ID.
        module_id: The module to add the item to.
        item_type: One of: Assignment, Quiz, File, Page, Discussion, SubHeader, ExternalUrl, ExternalTool.
        title: Display title for the item.
        content_id: Required for Assignment, Quiz, File, Discussion — the Canvas content ID.
        external_url: Required for ExternalUrl/ExternalTool — the URL.
        page_url: Required for Page — the page slug.
    """
    return add_module_item(course_id, module_id, item_type, title, content_id, external_url, page_url)


@mcp.tool()
@_safe_tool
def create_course_assignment(course_id: int, name: str, points_possible: float = 100, due_at: Optional[str] = None, description: str = "", submission_types: Optional[List[str]] = None, published: bool = False) -> str:
    """Create an assignment in a course. Created as a draft by default.

    Args:
        course_id: The Canvas course ID.
        name: Assignment name.
        points_possible: Max points (default 100).
        due_at: Due date in ISO 8601 with timezone. Optional.
        description: HTML or plain text description/instructions.
        submission_types: e.g. ['online_upload', 'online_text_entry']. Defaults to ['online_text_entry'].
        published: Whether to publish immediately. Default false (draft).
    """
    return create_assignment(course_id, name, points_possible, due_at, description, submission_types, published)


@mcp.tool()
@_safe_tool
def post_course_announcement(course_id: int, title: str, message: str) -> str:
    """Post an announcement to a course visible to all enrolled students.

    Args:
        course_id: The Canvas course ID.
        title: Announcement title/subject.
        message: Announcement body (HTML or plain text).
    """
    return post_announcement(course_id, title, message)


@mcp.tool()
@_safe_tool
def create_course_page(course_id: int, title: str, body: str = "", published: bool = False) -> str:
    """Create a content/wiki page in a course. Draft by default.

    Args:
        course_id: The Canvas course ID.
        title: Page title.
        body: Page content (HTML or plain text).
        published: Whether to publish immediately. Default false (draft).
    """
    return create_page(course_id, title, body, published)


@mcp.tool()
@_safe_tool
def get_assignment_grade_summary(course_id: int, assignment_id: int) -> str:
    """Get a grade summary for an assignment: total students, submitted, graded, missing, average/high/low scores. Instructor-only.

    Args:
        course_id: The Canvas course ID.
        assignment_id: The Canvas assignment ID.
    """
    return get_grade_summary(course_id, assignment_id)


def main():
    token = os.environ.get("CANVAS_API_TOKEN", "")
    base_url = os.environ.get("CANVAS_BASE_URL", "")
    if not token or not base_url:
        print("Error: CANVAS_API_TOKEN and CANVAS_BASE_URL environment variables are required.", file=sys.stderr)
        sys.exit(1)
    canvas_token_var.set(token)
    canvas_base_url_var.set(base_url)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
