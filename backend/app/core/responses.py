"""
app/core/responses.py

Uniform JSON response helpers for every API endpoint.

Standard envelope:
    {
        "success": true,
        "message": "...",
        "data": { ... },
        "meta":  { "page": 1, "limit": 20, "total": 100, ... }   // optional
    }

    {
        "success": false,
        "error": {
            "error_code": "RESUME_NOT_FOUND",
            "message": "Resume 'abc123' not found.",
            "details": { "resume_id": "abc123" }
        }
    }

Design:
  - All routes return via these helpers — never call jsonify() directly.
  - Consistent shape makes frontend error handling trivial.
  - Pagination meta included via success_list() helper.

Usage:
    from app.core.responses import success, success_list, error, created, no_content

    return success(data=resume.to_dict(), message="Resume parsed.")
    return success_list(data=jobs, total=200, page=1, limit=20)
    return error("Resume not found.", code="RESUME_NOT_FOUND", status=404)
    return created(data=job.to_dict(), message="Job created.")
    return no_content()
"""

from typing import Any

from flask import jsonify


# ─────────────────────────────────────────────────────────────────────────────
# Success responses
# ─────────────────────────────────────────────────────────────────────────────

def success(
    data: Any = None,
    message: str = "OK",
    status: int = 200,
    meta: dict | None = None,
) -> tuple:
    """
    Return a 200-range success response.

    Args:
        data:    The primary payload (dict, list, or None).
        message: Human-readable description.
        status:  HTTP status code (default 200).
        meta:    Optional metadata dict (pagination, etc.).

    Returns:
        Flask (Response, status_code) tuple.
    """
    body: dict[str, Any] = {
        "success": True,
        "message": message,
    }
    if data is not None:
        body["data"] = data
    if meta:
        body["meta"] = meta

    return jsonify(body), status


def success_list(
    data: list,
    total: int,
    page: int,
    limit: int,
    message: str = "OK",
) -> tuple:
    """
    Return a paginated list response.

    The meta block is always included:
        {
            "total":       100,
            "page":        1,
            "limit":       20,
            "total_pages": 5,
            "has_next":    true,
            "has_prev":    false
        }
    """
    total_pages = max(1, (total + limit - 1) // limit) if total > 0 else 1
    meta = {
        "total":       total,
        "page":        page,
        "limit":       limit,
        "total_pages": total_pages,
        "has_next":    page < total_pages,
        "has_prev":    page > 1,
    }
    return success(data=data, message=message, meta=meta)


def created(
    data: Any = None,
    message: str = "Created successfully.",
) -> tuple:
    """201 Created — use after POST that creates a new resource."""
    return success(data=data, message=message, status=201)


def no_content() -> tuple:
    """204 No Content — use after DELETE."""
    return "", 204


def accepted(message: str = "Request accepted.") -> tuple:
    """202 Accepted — use for async tasks that are queued."""
    return success(data=None, message=message, status=202)


# ─────────────────────────────────────────────────────────────────────────────
# Error responses
# ─────────────────────────────────────────────────────────────────────────────

def error(
    message: str,
    code: str = "ERROR",
    status: int = 400,
    details: dict | None = None,
) -> tuple:
    """
    Return a structured error response.

    Args:
        message: Human-readable error description.
        code:    Machine-readable error code slug.
        status:  HTTP status code.
        details: Optional extra context (field errors, resource IDs, etc.).

    Returns:
        Flask (Response, status_code) tuple.
    """
    body: dict[str, Any] = {
        "success": False,
        "error": {
            "error_code": code,
            "message":    message,
        },
    }
    if details:
        body["error"]["details"] = details

    return jsonify(body), status


def validation_error(errors: dict) -> tuple:
    """
    Return a 400 validation error with per-field error messages.

    Args:
        errors: Dict of field_name → [error_message, ...] from Marshmallow.

    Returns:
        Flask (Response, 400) tuple.
    """
    return error(
        message="Validation failed. Check the 'details.errors' field for specifics.",
        code="VALIDATION_ERROR",
        status=400,
        details={"errors": errors},
    )