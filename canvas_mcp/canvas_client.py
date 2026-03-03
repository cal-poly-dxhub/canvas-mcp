# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Canvas LMS REST API client.

All Canvas interactions go through this module. Credentials are read from
environment variables CANVAS_API_TOKEN and CANVAS_BASE_URL.
"""

from __future__ import annotations

import contextvars
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

import requests
from dateutil import parser as dateparser

logger = logging.getLogger(__name__)

# Per-request credentials — set once at startup for local (stdio) mode.
canvas_token_var: contextvars.ContextVar[str] = contextvars.ContextVar("canvas_token")
canvas_base_url_var: contextvars.ContextVar[str] = contextvars.ContextVar("canvas_base_url")


def _ctx_submit(pool: ThreadPoolExecutor, fn: Callable[..., Any], *args: Any, **kwargs: Any):
    """Submit *fn* to *pool*, propagating the current contextvars."""
    ctx = contextvars.copy_context()
    return pool.submit(ctx.run, fn, *args, **kwargs)


class CanvasConfigError(Exception):
    """Raised when required Canvas configuration is missing or invalid."""


_MAX_PER_PAGE = 100
_REQUEST_TIMEOUT_SECONDS = 30


def _get_base_url() -> str:
    try:
        url = canvas_base_url_var.get()
    except LookupError:
        raise CanvasConfigError("CANVAS_BASE_URL not set.")
    if not url:
        raise CanvasConfigError("CANVAS_BASE_URL not set.")
    return url.rstrip("/")


def _make_session() -> requests.Session:
    """Build a short-lived session using the caller's token."""
    try:
        token = canvas_token_var.get()
    except LookupError:
        raise CanvasConfigError("CANVAS_API_TOKEN not set.")
    if not token:
        raise CanvasConfigError("CANVAS_API_TOKEN not set.")
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}"})
    return session


_MAX_RETRIES = 3
_RETRY_BACKOFF_SECONDS = 1.0
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _request_with_retry(
    method: str, url: str, session: requests.Session, **kwargs: Any
) -> requests.Response:
    """Execute an HTTP request with retry on transient failures."""
    for attempt in range(1, _MAX_RETRIES + 1):
        resp = session.request(method, url, timeout=_REQUEST_TIMEOUT_SECONDS, **kwargs)
        if resp.status_code not in _RETRYABLE_STATUS_CODES or attempt == _MAX_RETRIES:
            resp.raise_for_status()
            return resp
        wait = _RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
        if resp.status_code == 429:
            wait = float(resp.headers.get("Retry-After", wait))
        logger.warning(
            "Retryable %s on %s %s (attempt %d/%d, waiting %.1fs)",
            resp.status_code, method, url, attempt, _MAX_RETRIES, wait,
        )
        time.sleep(wait)
    return resp  # unreachable, but satisfies type checker


def canvas_get(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """GET a Canvas API endpoint. Follows pagination and returns all results."""
    base = _get_base_url()
    url = f"{base}{path}"
    session = _make_session()
    resp = _request_with_retry("GET", url, session, params=params or {})
    data = resp.json()
    if isinstance(data, list):
        while resp.links.get("next", {}).get("url"):
            next_url = resp.links["next"]["url"]
            resp = _request_with_retry("GET", next_url, session)
            data.extend(resp.json())
    return data


def canvas_post(path: str, payload: Dict[str, Any]) -> Any:
    """POST to a Canvas API endpoint. Returns parsed JSON."""
    base = _get_base_url()
    url = f"{base}{path}"
    session = _make_session()
    resp = _request_with_retry("POST", url, session, json=payload)
    return resp.json()


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

_VALID_MODULE_ITEM_TYPES = frozenset(
    {"Assignment", "Quiz", "File", "Page", "Discussion", "SubHeader", "ExternalUrl", "ExternalTool"}
)

_VALID_SUBMISSION_TYPES = frozenset(
    {"online_text_entry", "online_upload", "online_quiz", "online_url", "media_recording", "none"}
)


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def list_courses() -> str:
    courses = canvas_get(
        "/api/v1/courses",
        params={"enrollment_state": "active", "per_page": _MAX_PER_PAGE},
    )
    out = [
        {"id": c["id"], "name": c.get("name"), "course_code": c.get("course_code"), "enrollment_term_id": c.get("enrollment_term_id")}
        for c in (courses or []) if c.get("id")
    ]
    return json.dumps({"courses": out})


def get_upcoming_assignments(days_ahead: int = 14) -> str:
    days_ahead = _clamp(days_ahead, 1, 60)
    horizon = datetime.now(timezone.utc) + timedelta(days=days_ahead)
    courses = canvas_get("/api/v1/courses", params={"enrollment_state": "active", "per_page": _MAX_PER_PAGE})
    valid_courses = [(c.get("id"), c.get("name") or f"Course {c.get('id')}") for c in (courses or []) if c.get("id")]

    def _fetch(cid: int, cname: str) -> List[Dict[str, Any]]:
        items = canvas_get(f"/api/v1/courses/{cid}/assignments", params={"bucket": "upcoming", "per_page": _MAX_PER_PAGE})
        results: List[Dict[str, Any]] = []
        for a in items or []:
            due_at = a.get("due_at")
            if not due_at:
                continue
            try:
                due = dateparser.parse(due_at)
            except (ValueError, OverflowError):
                continue
            if due and due <= horizon:
                results.append({"course_name": cname, "name": a.get("name"), "due_at": due.isoformat(), "points_possible": a.get("points_possible"), "submission_types": a.get("submission_types", []), "html_url": a.get("html_url"), "course_id": cid, "assignment_id": a.get("id")})
        return results

    out: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {_ctx_submit(pool, _fetch, cid, cname): cid for cid, cname in valid_courses}
        for future in as_completed(futures):
            try:
                out.extend(future.result())
            except Exception:
                logger.exception("Failed to fetch assignments for course %s", futures[future])
    out.sort(key=lambda x: x.get("due_at") or "")
    return json.dumps({"assignments": out})


def get_submission_status(course_id: int, assignment_id: int) -> str:
    sub = canvas_get(f"/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions/self")
    return json.dumps({"late": sub.get("late"), "missing": sub.get("missing"), "submitted_at": sub.get("submitted_at"), "graded_at": sub.get("graded_at"), "workflow_state": sub.get("workflow_state"), "score": sub.get("score")})


def get_my_grades(course_id: int) -> str:
    with ThreadPoolExecutor(max_workers=2) as pool:
        subs_future = _ctx_submit(pool, canvas_get, f"/api/v1/courses/{course_id}/students/submissions", {"student_ids[]": "self", "per_page": _MAX_PER_PAGE})
        assignments_future = _ctx_submit(pool, canvas_get, f"/api/v1/courses/{course_id}/assignments", {"per_page": _MAX_PER_PAGE})
        subs = subs_future.result()
        assignments = assignments_future.result()
    name_map = {a.get("id"): a.get("name", "") for a in (assignments or []) if a.get("id")}
    out = [{"assignment_id": s.get("assignment_id"), "assignment_name": name_map.get(s.get("assignment_id"), ""), "score": s.get("score"), "grade": s.get("grade"), "submitted_at": s.get("submitted_at"), "late": s.get("late"), "missing": s.get("missing"), "workflow_state": s.get("workflow_state")} for s in (subs or [])]
    return json.dumps({"grades": out})


def get_todo_items() -> str:
    items = canvas_get("/api/v1/users/self/todo", params={"per_page": _MAX_PER_PAGE})
    out = [{"type": item.get("type"), "context_name": item.get("context_name"), "assignment_name": (item.get("assignment") or {}).get("name"), "due_at": (item.get("assignment") or {}).get("due_at"), "points_possible": (item.get("assignment") or {}).get("points_possible"), "html_url": item.get("html_url"), "course_id": item.get("course_id"), "assignment_id": (item.get("assignment") or {}).get("id")} for item in (items or [])]
    return json.dumps({"todo_items": out})


def create_canvas_event(title: str, start_at: str, end_at: str) -> str:
    if not (title and start_at and end_at):
        return json.dumps({"error": "title, start_at, and end_at are all required"})
    me = canvas_get("/api/v1/users/self")
    user_id = me.get("id")
    if not user_id:
        return json.dumps({"error": "Could not determine current user ID"})
    res = canvas_post("/api/v1/calendar_events", {"calendar_event": {"context_code": f"user_{user_id}", "title": title, "start_at": start_at, "end_at": end_at}})
    return json.dumps({"id": res.get("id"), "title": title, "start_at": start_at, "end_at": end_at, "html_url": res.get("html_url")})


def search_course_files(course_id: int, search_term: str = "") -> str:
    params: Dict[str, Any] = {"per_page": 50}
    if search_term:
        params["search_term"] = search_term
    files = canvas_get(f"/api/v1/courses/{course_id}/files", params=params)
    out = [{"id": f["id"], "display_name": f.get("display_name"), "url": f.get("url"), "size": f.get("size"), "content_type": f.get("content-type"), "updated_at": f.get("updated_at")} for f in (files or [])]
    return json.dumps({"files": out})


def create_module(course_id: int, name: str, position: Optional[int] = None) -> str:
    payload: Dict[str, Any] = {"module": {"name": name}}
    if position is not None:
        payload["module"]["position"] = position
    mod = canvas_post(f"/api/v1/courses/{course_id}/modules", payload)
    return json.dumps({"id": mod.get("id"), "name": mod.get("name"), "position": mod.get("position")})


def add_module_item(course_id: int, module_id: int, item_type: str, title: str, content_id: Optional[int] = None, external_url: Optional[str] = None, page_url: Optional[str] = None) -> str:
    if item_type not in _VALID_MODULE_ITEM_TYPES:
        return json.dumps({"error": f"Invalid item_type '{item_type}'. Must be one of: {sorted(_VALID_MODULE_ITEM_TYPES)}"})
    item: Dict[str, Any] = {"title": title, "type": item_type}
    if content_id is not None:
        item["content_id"] = content_id
    if page_url:
        item["page_url"] = page_url
    if external_url:
        item["external_url"] = external_url
    res = canvas_post(f"/api/v1/courses/{course_id}/modules/{module_id}/items", {"module_item": item})
    return json.dumps({"id": res.get("id"), "title": res.get("title"), "type": res.get("type"), "position": res.get("position")})


def create_assignment(course_id: int, name: str, points_possible: float = 100, due_at: Optional[str] = None, description: str = "", submission_types: Optional[List[str]] = None, published: bool = False) -> str:
    sub_types = submission_types or ["online_text_entry"]
    invalid = set(sub_types) - _VALID_SUBMISSION_TYPES
    if invalid:
        return json.dumps({"error": f"Invalid submission_types: {sorted(invalid)}. Valid: {sorted(_VALID_SUBMISSION_TYPES)}"})
    assignment: Dict[str, Any] = {"name": name, "points_possible": max(0, points_possible), "description": description, "submission_types": sub_types, "published": published}
    if due_at:
        assignment["due_at"] = due_at
    res = canvas_post(f"/api/v1/courses/{course_id}/assignments", {"assignment": assignment})
    return json.dumps({"id": res.get("id"), "name": res.get("name"), "due_at": res.get("due_at"), "points_possible": res.get("points_possible"), "html_url": res.get("html_url"), "published": res.get("published")})


def post_announcement(course_id: int, title: str, message: str) -> str:
    res = canvas_post(f"/api/v1/courses/{course_id}/discussion_topics", {"title": title, "message": message, "is_announcement": True, "published": True})
    return json.dumps({"id": res.get("id"), "title": res.get("title"), "html_url": res.get("html_url"), "posted_at": res.get("posted_at")})


def create_page(course_id: int, title: str, body: str = "", published: bool = False) -> str:
    res = canvas_post(f"/api/v1/courses/{course_id}/pages", {"wiki_page": {"title": title, "body": body, "published": published}})
    return json.dumps({"page_id": res.get("page_id"), "url": res.get("url"), "title": res.get("title"), "html_url": res.get("html_url")})


def get_grade_summary(course_id: int, assignment_id: int) -> str:
    subs = canvas_get(f"/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions", params={"per_page": _MAX_PER_PAGE})
    graded = submitted = missing = total = 0
    scores: List[float] = []
    for s in subs or []:
        total += 1
        if s.get("workflow_state") == "graded":
            graded += 1
            if s.get("score") is not None:
                scores.append(float(s["score"]))
        if s.get("submitted_at"):
            submitted += 1
        if s.get("missing"):
            missing += 1
    return json.dumps({"total_students": total, "submitted": submitted, "graded": graded, "missing": missing, "average_score": round(sum(scores) / len(scores), 2) if scores else None, "high_score": max(scores) if scores else None, "low_score": min(scores) if scores else None})
