"""
app/repositories/ats_score.py — AtsScore-specific data access methods.

FIXES APPLIED:
  AR-01 — upsert() did not update application_id when an existing score was
           found. If an application was linked after the initial standalone
           score, the link was silently dropped. Fixed by adding
           `existing.application_id = score.application_id` to the update path.

  SC-03 — list_filtered() did not exist at all. The scoring API's
           GET /scores/ endpoint called repo.list_filtered(...) which raised
           AttributeError on every request. Added the full implementation.
"""

import logging

from sqlalchemy import and_

from app.core.database import db
from app.models.ats_score import AtsScore
from app.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class AtsScoreRepository(BaseRepository[AtsScore]):
    """Repository for AtsScore model."""

    model = AtsScore

    def get_by_resume_and_job(
        self, resume_id: str, job_id: str
    ) -> AtsScore | None:
        """Fetch existing score for a resume × job pair (unique per pair)."""
        return (
            db.session.query(AtsScore)
            .filter(
                AtsScore.resume_id == resume_id,
                AtsScore.job_id    == job_id,
            )
            .first()
        )

    def upsert(self, score: AtsScore) -> AtsScore:
        """
        Insert a new score or update an existing one for the same resume×job pair.

        FIX AR-01: The original implementation omitted application_id from the
        field updates. When score_resume_job() was called at apply-time (with
        an application_id), the link between the AtsScore and the Application
        was silently dropped if a standalone score had been computed earlier.
        """
        existing = self.get_by_resume_and_job(score.resume_id, score.job_id)
        if existing:
            existing.semantic_score        = score.semantic_score
            existing.keyword_score         = score.keyword_score
            existing.experience_score      = score.experience_score
            existing.section_quality_score = score.section_quality_score
            existing.final_score           = score.final_score
            existing.score_label           = score.score_label
            existing.semantic_available    = score.semantic_available
            existing.matched_skills        = score.matched_skills
            existing.missing_skills        = score.missing_skills
            existing.extra_skills          = score.extra_skills
            existing.improvement_tips      = score.improvement_tips
            existing.summary_text          = score.summary_text
            existing.weights_used          = score.weights_used
            # FIX AR-01: was missing — application link was silently lost on re-score
            if score.application_id is not None:
                existing.application_id = score.application_id
            db.session.add(existing)
            return existing
        else:
            db.session.add(score)
            db.session.flush()
            return score

    def find_by_resume_job(
        self,
        resume_id: str,
        job_id: str,
    ) -> AtsScore | None:
        """
        Return the most recent AtsScore for a resume+job pair, or None.

        Used by AtsScorerService to avoid re-scoring unchanged resume+job pairs.
        """
        try:
            return (
                AtsScore.query
                .filter_by(resume_id=resume_id, job_id=job_id)
                .order_by(AtsScore.created_at.desc())
                .first()
            )
        except Exception as exc:
            logger.warning(
                "find_by_resume_job failed for resume=%s job=%s: %s",
                resume_id, job_id, exc,
            )
            return None

    def get_top_for_job(
        self,
        job_id: str,
        top_n: int = 10,
        min_score: float = 0.0,
    ) -> list[AtsScore]:
        """
        Return top N scores for a job, ordered by final_score DESC.

        Used by recruiter dashboard — top candidates per job.
        """
        return (
            db.session.query(AtsScore)
            .filter(
                AtsScore.job_id      == job_id,
                AtsScore.final_score >= min_score,
            )
            .order_by(AtsScore.final_score.desc())
            .limit(top_n)
            .all()
        )

    def get_top_for_resume(
        self,
        resume_id: str,
        top_n: int = 10,
    ) -> list[AtsScore]:
        """
        Return top N scores for a resume (job recommendations), highest first.
        """
        return (
            db.session.query(AtsScore)
            .filter(AtsScore.resume_id == resume_id)
            .order_by(AtsScore.final_score.desc())
            .limit(top_n)
            .all()
        )

    def list_by_job(
        self,
        job_id: str,
        min_score: float | None = None,
        score_label: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[AtsScore], int]:
        """Paginated scores for a job with optional score filters."""
        query = db.session.query(AtsScore).filter(AtsScore.job_id == job_id)

        if min_score is not None:
            query = query.filter(AtsScore.final_score >= min_score)
        if score_label:
            query = query.filter(AtsScore.score_label == score_label)

        total = query.count()
        items = (
            query
            .order_by(AtsScore.final_score.desc())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )
        return items, total

    def list_filtered(
        self,
        page: int = 1,
        limit: int = 20,
        resume_id: str | None = None,
        job_id: str | None = None,
        min_score: float | None = None,
        max_score: float | None = None,
        score_label: str | None = None,
    ) -> tuple[list[AtsScore], int]:
        """
        Paginated, multi-filter query for stored ATS scores.

        FIX SC-03: This method was entirely missing. The GET /scores/ endpoint
        called repo.list_filtered(...) on every request, raising AttributeError
        every time. This is the full implementation.

        Args:
            page:        1-based page number.
            limit:       Records per page (capped by caller's MAX_PAGE_SIZE).
            resume_id:   Filter by resume UUID (optional).
            job_id:      Filter by job UUID (optional).
            min_score:   Lower bound on final_score, inclusive (optional).
            max_score:   Upper bound on final_score, inclusive (optional).
            score_label: Exact match on score_label enum value (optional).

        Returns:
            (items, total) — list of AtsScore ORM objects and total count
            before pagination.
        """
        query = db.session.query(AtsScore)

        if resume_id:
            query = query.filter(AtsScore.resume_id == resume_id)
        if job_id:
            query = query.filter(AtsScore.job_id == job_id)
        if min_score is not None:
            query = query.filter(AtsScore.final_score >= min_score)
        if max_score is not None:
            query = query.filter(AtsScore.final_score <= max_score)
        if score_label:
            query = query.filter(AtsScore.score_label == score_label)

        total = query.count()
        items = (
            query
            .order_by(AtsScore.final_score.desc(), AtsScore.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )
        return items, total
    
    def get_missing_skills_for_candidate(self, candidate_id: str) -> list[str]:
        """Aggregate all missing skills from a candidate's ATS scores."""
        from app.models.application import Application
        results = (
            db.session.query(self.model)
            .join(Application, Application.resume_id == self.model.resume_id)
            .filter(Application.candidate_id == candidate_id)
            .with_entities(self.model.missing_skills)
            .all()
        )
        all_missing = []
        for (skills_json,) in results:
            if skills_json:
                import json
                try:
                    parsed = json.loads(skills_json)
                    if isinstance(parsed, list):
                        all_missing.extend(parsed)
                except Exception:
                    pass
        return all_missing