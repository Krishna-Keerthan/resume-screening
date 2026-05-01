
"""
app/repositories/recruiter.py — Recruiter-specific data access methods.
"""

import logging

from sqlalchemy import or_

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

    def email_exists(self, email: str) -> bool:
        return self.get_by_email(email) is not None

    def list_active(
        self,
        page: int = 1,
        limit: int = 20,
        search: str | None = None,
        company_name: str | None = None,
    ) -> tuple[list[Recruiter], int]:
        query = self.base_query().filter(Recruiter.is_active == True)  # noqa: E712

        if search:
            pattern = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    Recruiter.full_name.ilike(pattern),
                    Recruiter.company_name.ilike(pattern),
                    Recruiter.email.ilike(pattern),
                )
            )
        if company_name:
            query = query.filter(Recruiter.company_name.ilike(f"%{company_name.strip()}%"))

        total = query.count()
        items = (
            query
            .order_by(Recruiter.platform_rank.asc(), Recruiter.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )
        return items, total

    def get_with_jobs(self, recruiter_id: str) -> Recruiter | None:
        """Fetch recruiter with all jobs eagerly loaded."""
        from sqlalchemy.orm import joinedload
        return (
            db.session.query(Recruiter)
            .options(joinedload(Recruiter.jobs))
            .filter(Recruiter.id == recruiter_id)
            .first()
        )

    def update_metrics(self, recruiter_id: str, jobs_posted: int, total_hires: int) -> None:
        """Update denormalised recruiter metrics."""
        recruiter = self.get_by_id(recruiter_id)
        if recruiter:
            recruiter.total_jobs_posted = jobs_posted
            recruiter.total_hires       = total_hires
            db.session.add(recruiter)