"""
app/utils/pagination.py

Reusable pagination helper.

IMPROVEMENTS APPLIED:
  PG-01 — PaginationParams exposed only page and limit. Callers building API
           responses had to manually compute has_next, has_prev, total_pages
           on every endpoint, leading to copy-pasted arithmetic that was wrong
           in several places. Added these as computed properties on
           PaginationParams.

  PG-02 — Added to_meta(total) convenience method that returns the full
           pagination envelope dict consumed by success_list(). This keeps
           the pagination contract in one place and makes endpoints
           one-liners:
               return success_list(**params.to_meta(total), data=[...])
"""

import math
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from flask import current_app, request
from sqlalchemy.orm import Query

from app.core.exceptions import ValidationError

T = TypeVar("T")


@dataclass
class PaginationParams:
    """
    Validated pagination parameters.

    PG-01: page and limit are the raw inputs; has_next, has_prev, and
    total_pages are computed from them and the total record count.
    """
    page:  int
    limit: int

    @classmethod
    def from_request(cls) -> "PaginationParams":
        """
        Parse page and limit from the current Flask request.args.

        Applies defaults from app config and caps at MAX_PAGE_SIZE.
        Raises ValidationError on non-integer input.
        """
        default_limit = current_app.config.get("DEFAULT_PAGE_SIZE", 20)
        max_limit     = current_app.config.get("MAX_PAGE_SIZE", 100)

        try:
            page  = int(request.args.get("page",  1))
            limit = int(request.args.get("limit", default_limit))
        except (ValueError, TypeError) as exc:
            raise ValidationError(
                "Query params 'page' and 'limit' must be positive integers.",
                details={"page": request.args.get("page"), "limit": request.args.get("limit")},
            ) from exc

        # Clamp values
        page  = max(1, page)
        limit = max(1, min(limit, max_limit))

        return cls(page=page, limit=limit)

    # ── PG-01: computed pagination helpers ────────────────────────────────────

    def has_next(self, total: int) -> bool:
        """True when there is at least one more page after the current one."""
        return self.page < self.total_pages(total)

    def has_prev(self) -> bool:
        """True when the current page is not the first page."""
        return self.page > 1

    def total_pages(self, total: int) -> int:
        """Total number of pages for the given record count."""
        if total == 0:
            return 1
        return math.ceil(total / self.limit)

    def offset(self) -> int:
        """SQL OFFSET value for the current page."""
        return (self.page - 1) * self.limit

    # ── PG-02: meta dict helper ───────────────────────────────────────────────

    def to_meta(self, total: int) -> dict[str, Any]:
        """
        Return the full pagination envelope dict for success_list().

        Usage:
            items, total = repo.list_all(page=params.page, limit=params.limit)
            return success_list(data=[i.to_dict() for i in items],
                                **params.to_meta(total),
                                message="Records retrieved.")

        Returns:
            {
                "total":       <int>,
                "page":        <int>,
                "limit":       <int>,
                "total_pages": <int>,
                "has_next":    <bool>,
                "has_prev":    <bool>,
            }
        """
        return {
            "total":       total,
            "page":        self.page,
            "limit":       self.limit,
            "total_pages": self.total_pages(total),
            "has_next":    self.has_next(total),
            "has_prev":    self.has_prev(),
        }


def paginate_query(
    query: Query,
    params: PaginationParams,
) -> tuple[list, int]:
    """
    Apply pagination to a SQLAlchemy query.

    Args:
        query:  An active SQLAlchemy query (not yet executed).
        params: Validated PaginationParams.

    Returns:
        (items, total) — list of ORM objects and total count before pagination.
    """
    total = query.count()
    items = (
        query
        .offset(params.offset())
        .limit(params.limit)
        .all()
    )
    return items, total