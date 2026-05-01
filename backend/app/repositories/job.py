
"""
app/repositories/job.py — Job-specific data access methods.
"""

import logging


from app.core.database import db
from app.models.enums import JobStatus
from app.models.job import Job
from app.repositories.base import BaseRepository
from sqlalchemy import or_
logger = logging.getLogger(__name__)


class JobRepository(BaseRepository[Job]):
    """Repository for Job model — includes soft-delete and search support."""

    model = Job

    def list_active(
        self,
        page: int = 1,
        limit: int = 20,
        search: str | None = None,
        location: str | None = None,
        job_type: str | None = None,
        recruiter_id: str | None = None,
        min_experience: float | None = None,
        max_experience: float | None = None,
    ) -> tuple[list[Job], int]:
        """
        Paginated active jobs with optional filters.

        Automatically excludes soft-deleted jobs (is_deleted=False).
        """
        query = (
            db.session.query(Job)
            .filter(
                Job.is_deleted == False,       # noqa: E712
                Job.status == JobStatus.ACTIVE.value,
            )
        )

        if search:
            pattern = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    Job.title.ilike(pattern),
                    Job.company.ilike(pattern),
                    Job.description.ilike(pattern),
                )
            )
        if location:
            query = query.filter(Job.location.ilike(f"%{location.strip()}%"))
        if job_type:
            query = query.filter(Job.job_type == job_type)
        if recruiter_id:
            query = query.filter(Job.recruiter_id == recruiter_id)
        if min_experience is not None:
            query = query.filter(Job.experience_years >= min_experience)
        if max_experience is not None:
            query = query.filter(Job.experience_years <= max_experience)

        total = query.count()
        items = (
            query
            .order_by(Job.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )
        return items, total

    def list_by_recruiter(
            self,
            recruiter_id: str,
            status: str | None = None,
            page: int | None = None,
            limit: int | None = None,
            include_closed: bool = False,
            with_count: bool = True,
        ):
        """
        Fetch jobs for a recruiter.

        Supports:
        - optional status filtering
        - optional pagination
        - include_closed for analytics
        - returning list only (service usage)
        """

        query = (
            db.session.query(Job)
            .filter(
                Job.recruiter_id == recruiter_id,
                Job.is_deleted == False,  # noqa: E712
            )
        )

        # If not including closed jobs, default to ACTIVE only
        if not include_closed and not status:
            query = query.filter(Job.status == JobStatus.ACTIVE.value)

        if status:
            query = query.filter(Job.status == status)

        query = query.order_by(Job.created_at.desc())

        # ── Pagination branch (API usage) ─────────────────────────────
        if page is not None and limit is not None:
            total = query.count()
            items = (
                query
                .offset((page - 1) * limit)
                .limit(limit)
                .all()
            )
            return (items, total) if with_count else items

        # ── Non-paginated branch (Analytics usage) ─────────────────────
        return query.all()


    def get_by_ids(self, job_ids: list[str]) -> list[Job]:
        """Fetch multiple jobs by a list of IDs."""
        return (
            db.session.query(Job)
            .filter(Job.id.in_(job_ids), Job.is_deleted == False)  # noqa: E712
            .all()
        )

    def increment_applicant_count(self, job_id: str) -> None:
        """Thread-safe increment of applicant_count."""
        db.session.query(Job).filter(Job.id == job_id).update(
            {Job.applicant_count: Job.applicant_count + 1},
            synchronize_session=False,
        )

    def decrement_applicant_count(self, job_id: str) -> None:
        """Decrement applicant_count (floor at 0)."""
        job = self.get_by_id(job_id)
        if job and job.applicant_count > 0:
            job.applicant_count -= 1
            db.session.add(job)

    def find_duplicates(self, title: str, company: str, recruiter_id: str) -> list[Job]:
        """
        Find potential duplicate jobs for smart posting validation.

        Checks for active jobs with similar title + same company + same recruiter.
        """
        pattern = f"%{title.strip()}%"
        return (
            db.session.query(Job)
            .filter(
                Job.recruiter_id == recruiter_id,
                Job.company.ilike(company.strip()),
                Job.title.ilike(pattern),
                Job.status.in_([JobStatus.ACTIVE.value, JobStatus.PAUSED.value]),
                Job.is_deleted == False,  # noqa: E712
            )
            .all()
        )