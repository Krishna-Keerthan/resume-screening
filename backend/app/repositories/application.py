
"""
app/repositories/application.py — Application-specific data access methods.
"""

import logging

from app.core.database import db
from app.models.application import Application
from app.models.enums import ApplicationStage
from app.repositories.base import BaseRepository
from sqlalchemy.orm import joinedload

logger = logging.getLogger(__name__)


class ApplicationRepository(BaseRepository[Application]):
    """Repository for Application model."""

    model = Application

    def get_by_candidate_and_job(
        self, candidate_id: str, job_id: str
    ) -> Application | None:
        """Check if a candidate has already applied to a specific job."""
        return (
            db.session.query(Application)
            .filter(
                Application.candidate_id == candidate_id,
                Application.job_id == job_id,
            )
            .first()
        )

    def application_exists(self, candidate_id: str, job_id: str) -> bool:
        return self.get_by_candidate_and_job(candidate_id, job_id) is not None

    def list_by_job(self, job_id, stage=None, page=1, limit=20):
        query = (
            db.session.query(Application)
            .options(
                joinedload(Application.candidate),
                joinedload(Application.ats_score),
            )
            .filter(Application.job_id == job_id)
        )
        if stage:
            query = query.filter(Application.stage == stage)
        total = query.count()
        items = (
            query
            .order_by(Application.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )
        return items, total

    def list_by_candidate(self, candidate_id, stage=None, page=1, limit=20):
        query = (
            db.session.query(Application)
            .options(
                joinedload(Application.job),
                joinedload(Application.ats_score),
            )
            .filter(Application.candidate_id == candidate_id)
        )
        if stage:
            query = query.filter(Application.stage == stage)
        total = query.count()
        items = (
            query
            .order_by(Application.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )
        return items, total

    def get_top_applicants(
        self, job_id: str, top_n: int = 3
    ) -> list[Application]:
        """
        Return top N applicants for a job, ordered by ATS final_score DESC.

        Used by recruiter dashboard to show top candidates per job card.
        Requires a JOIN on ats_scores table.
        """
        from app.models.ats_score import AtsScore
        return (
            db.session.query(Application)
            .join(AtsScore, AtsScore.application_id == Application.id, isouter=True)
            .filter(Application.job_id == job_id)
            .order_by(AtsScore.final_score.desc().nullslast())
            .limit(top_n)
            .all()
        )

    def count_by_stage(self, job_id: str) -> dict[str, int]:
        """
        Return a breakdown of application counts by stage for a job.

        Used by recruiter analytics.
        Returns: {"applied": 10, "shortlisted": 3, ...}
        """
        from sqlalchemy import func
        rows = (
            db.session.query(Application.stage, func.count(Application.id))
            .filter(Application.job_id == job_id)
            .group_by(Application.stage)
            .all()
        )
        return {stage: count for stage, count in rows}

    def get_applications_with_scores(self, candidate_id: str) -> list:
        """Get all applications with their ATS scores for win rate analysis."""
        from app.models.ats_score import AtsScore
        return (
            db.session.query(self.model, AtsScore)
            .outerjoin(AtsScore, (AtsScore.resume_id == self.model.resume_id) &
                                (AtsScore.job_id == self.model.job_id))
            .filter(self.model.candidate_id == candidate_id)
            .all()
        )

