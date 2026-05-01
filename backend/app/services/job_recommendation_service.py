"""
app/services/job_recommendation_service.py

Job recommendation engine — returns the top-N best-fitting jobs for
a given candidate resume using pre-computed ATS scores + live scoring
for new jobs.

Two-phase strategy:
  1. Fast-path: Look up cached ATS scores in ats_scores table.
     (populated whenever a full score has been run for this resume)
  2. Re-score: For active jobs that have NO existing score, run the
     full AtsScorerService pipeline and cache the result.
  3. Rank by final_score DESC, apply filters, return top-N.

Filters:
  - Only ACTIVE jobs.
  - Optional: location filter, job_type filter, min_score threshold.
  - Soft-deleted jobs are excluded by the repository's base_query.

Usage:
    from app.services.job_recommendation_service import JobRecommendationService

    svc = JobRecommendationService(
        ats_scorer=scorer,
        ats_score_repo=ats_repo,
        job_repo=job_repo,
        top_n=10,
    )

    recommendations = svc.recommend(
        resume=resume_obj,
        top_n=10,
        location_filter=None,
        min_score=0.40,
        rescore_new=True,
    )
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from app.models.job import Job

logger = logging.getLogger(__name__)


@dataclass
class JobRecommendation:
    """A single job recommendation."""
    job_id:        str
    title:         str
    company:       str
    location:      str
    job_type:      str
    final_score:   float
    score_label:   str
    matched_skills: list = field(default_factory=list)
    missing_skills: list = field(default_factory=list)
    summary_text:   str = ""
    salary_min:     Optional[int] = None
    salary_max:     Optional[int] = None
    salary_currency: str = "USD"


class JobRecommendationService:
    """
    Recommends jobs for a candidate using cached ATS scores + live re-scoring.
    """

    def __init__(
        self,
        ats_scorer,
        ats_score_repo,
        job_repo,
        top_n: int = 10,
    ):
        self._scorer   = ats_scorer
        self._ats_repo = ats_score_repo
        self._job_repo = job_repo
        self._top_n    = top_n

    def recommend(
        self,
        resume,
        top_n: Optional[int] = None,
        location_filter: Optional[str] = None,
        job_type_filter: Optional[str] = None,
        min_score: float = 0.0,
        rescore_new: bool = True,
        use_llm: bool = False,  # LLM off by default for batch operations
        status_filter: Optional[str] = None,
    ) -> list[JobRecommendation]:
        """
        Return top-N job recommendations for a resume.

        Args:
            resume:          Resume ORM object.
            top_n:           Max recommendations to return.
            location_filter: Optional location string filter.
            job_type_filter: Optional job_type enum value filter.
            min_score:       Minimum final_score to include.
            rescore_new:     Whether to score jobs with no cached score.
            use_llm:         Whether to use LLM in new scoring calls.

        Returns:
            List of JobRecommendation sorted by score DESC.
        """
        limit = top_n or self._top_n
        try:
            return self._run(
                resume, limit, location_filter, job_type_filter,
                min_score, rescore_new, use_llm, status_filter,
            )
        except Exception as exc:
            logger.exception(
                "Job recommendation failed for resume=%s", resume.id
            )
            return []

    def _run(
        self,
        resume,
        top_n: int,
        location_filter: Optional[str],
        job_type_filter: Optional[str],
        min_score: float,
        rescore_new: bool,
        use_llm: bool,
        status_filter: Optional[str] = None
    ) -> list[JobRecommendation]:
        from app.models.enums import JobStatus

        # ── 1. Fetch cached scores ─────────────────────────────────────────────
        cached_scores = self._ats_repo.get_top_for_resume(
            resume_id=resume.id,
            top_n=top_n * 3,  # Over-fetch to allow filtering
        )

        scored_job_ids = {s.job_id for s in cached_scores}

        # ── 2. Find active jobs not yet scored ────────────────────────────────
        if rescore_new:
            active_jobs, _ = self._job_repo.list_active(
                page=1,
                limit=50,
            )

            flattened_jobs = [j for j in active_jobs if isinstance(j, Job)]
            

            unscored = [j for j in flattened_jobs if j.id not in scored_job_ids]
            # Score up to 20 new jobs per call to keep latency reasonable
            for job in unscored[:20]:
                try:
                    self._scorer.score_resume_job(
                        resume=resume,
                        job=job,
                        use_llm=use_llm,
                    )
                except Exception as exc:
                    logger.warning("Skipping job %s scoring: %s", job.id, exc)

            # Refresh cached scores
            cached_scores = self._ats_repo.get_top_for_resume(
                resume_id=resume.id,
                top_n=top_n * 3,
            )

        # ── 3. Load job objects for filtering ────────────────────────────────
        job_id_list = [s.job_id for s in cached_scores]
        if not job_id_list:
            return []

        jobs_by_id = {
            j.id: j
            for j in self._job_repo.get_by_ids(job_id_list)
        }

        # ── 4. Build and filter recommendations ───────────────────────────────
        recommendations: list[JobRecommendation] = []
        for score_record in cached_scores:
            job = jobs_by_id.get(score_record.job_id)
            if not job:
                continue
            if status_filter:
                if job.status != status_filter:
                    continue
            else:
                if job.status != JobStatus.ACTIVE:
                    continue
            if score_record.final_score < min_score:
                continue
            if location_filter and location_filter.lower() not in job.location.lower():
                continue
            if job_type_filter and job.job_type != job_type_filter:
                continue

            recommendations.append(JobRecommendation(
                job_id=job.id,
                title=job.title,
                company=job.company,
                location=job.location,
                job_type=job.job_type,
                final_score=score_record.final_score,
                score_label=score_record.score_label,
                matched_skills=score_record.matched_skills_list,
                missing_skills=score_record.missing_skills_list,
                summary_text=score_record.summary_text or "",
                salary_min=job.salary_min,
                salary_max=job.salary_max,
                salary_currency=job.salary_currency,
            ))

        # ── 5. Sort and return top-N ──────────────────────────────────────────
        recommendations.sort(key=lambda r: r.final_score, reverse=True)
        return recommendations[:top_n]