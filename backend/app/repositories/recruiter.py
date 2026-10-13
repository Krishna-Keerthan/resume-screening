
"""
app/repositories/recruiter.py — Recruiter-specific data access methods.
"""

import logging

from app.core.database import db
from app.models.recruiter import Recruiter
from app.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class RecruiterRepository(BaseRepository[Recruiter]):
    """Repository for Recruiter model."""

    model = Recruiter

    def get_by_email(self, email: str) -> Recruiter | None:
        return (
            db.session.query(Recruiter)
            .filter(Recruiter.email.ilike(email.strip()))
            .first()
        )

    def get_active_by_id(self, recruiter_id: str) -> Recruiter | None:
        """Fetch a recruiter that is active and not deleted."""
        return (
            self.base_query()
            .filter(Recruiter.id == recruiter_id, Recruiter.is_active == True)  # noqa: E712
            .first()
        )

    def email_exists(self, email: str) -> bool:
        return self.get_by_email(email) is not None
