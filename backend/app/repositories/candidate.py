"""
app/repositories/candidate.py — Candidate-specific data access methods.

FIXES APPLIED:
  BUG #3 — list_active() now uses self.base_query() as its starting point.

  Previously it built its own db.session.query(Candidate) and only filtered
  is_active == True. This bypassed the SoftDeleteMixin filter in base_query()
  which adds .filter(Candidate.is_deleted == False).

  Result: a record that was soft-deleted (is_deleted=True) would still appear
  in list_active() responses, and the behavior differed from all other
  repository methods that use base_query() correctly.

  The fix starts from self.base_query() which:
    1. Filters is_deleted == False (from SoftDeleteMixin)
    2. Can be extended with additional filters cleanly
    3. Matches the behavior of list_paginated() in BaseRepository
"""

import logging
from typing import Any

from sqlalchemy import or_

from app.core.database import db
from app.models.candidate import Candidate
from app.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class CandidateRepository(BaseRepository[Candidate]):
    """Repository for Candidate model — extends BaseRepository with domain queries."""

    model = Candidate

    def get_by_email(self, email: str) -> Candidate | None:
        """Fetch a candidate by email address (case-insensitive)."""
        return (
            db.session.query(Candidate)
            .filter(Candidate.email.ilike(email.strip()))
            .first()
        )

    def email_exists(self, email: str) -> bool:
        """Return True if a candidate with this email already exists."""
        return self.get_by_email(email) is not None

    def list_active(
        self,
        page: int = 1,
        limit: int = 20,
        search: str | None = None,
        open_to_work: bool | None = None,
        location: str | None = None,
    ) -> tuple[list[Candidate], int]:
        """
        Paginated list of active, non-deleted candidates with optional filters.

        FIX: Now starts from self.base_query() which correctly applies
        the is_deleted == False filter from SoftDeleteMixin.
        Previously this built its own query and missed that filter.

        Args:
            page, limit:   Pagination.
            search:        Full-text search on full_name, email, headline.
            open_to_work:  Filter by job-seeking status.
            location:      Filter by location (ILIKE).

        Returns:
            (items, total) tuple.
        """
        # FIX: use base_query() — applies is_deleted == False automatically
        query = (
            self.base_query()
            .filter(Candidate.is_active == True)  # noqa: E712
        )

        if search:
            pattern = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    Candidate.full_name.ilike(pattern),
                    Candidate.email.ilike(pattern),
                    Candidate.headline.ilike(pattern),
                )
            )

        if open_to_work is not None:
            query = query.filter(Candidate.open_to_work == open_to_work)

        if location:
            query = query.filter(Candidate.location.ilike(f"%{location.strip()}%"))

        total = query.count()
        items = (
            query
            .order_by(Candidate.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )

        logger.debug(
            "list_active",
            extra={
                "total":    total,
                "page":     page,
                "returned": len(items),
            },
        )
        return items, total

    def get_with_resumes(self, candidate_id: str) -> Candidate | None:
        """Fetch candidate with resumes eagerly loaded."""
        from sqlalchemy.orm import joinedload
        return (
            db.session.query(Candidate)
            .options(joinedload(Candidate.resumes))
            .filter(Candidate.id == candidate_id)
            .first()
        )