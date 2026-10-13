"""
app/repositories/candidate.py — Candidate-specific data access methods.
"""

import logging
from typing import Any

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

    def get_active_by_id(self, candidate_id: str) -> Candidate | None:
        """Fetch a candidate that is active and not deleted."""
        return (
            self.base_query()
            .filter(Candidate.id == candidate_id, Candidate.is_active == True)  # noqa: E712
            .first()
        )

    def email_exists(self, email: str) -> bool:
        """Return True if a candidate with this email already exists."""
        return self.get_by_email(email) is not None
