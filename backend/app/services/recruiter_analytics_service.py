"""
app/services/recruiter_analytics_service.py

Recruiter analytics service — computes dashboard metrics and pipeline
statistics for a recruiter's job postings.

Metrics provided:
  - Pipeline funnel: application counts per stage across all jobs.
  - Top performing jobs: sorted by applicant count or avg score.
  - Score distribution: how many candidates fall into each tier.
  - Hiring velocity: avg days from application to hire (last 30 days).
  - Skills demand report: most required skills across active jobs.

All queries are delegated to repositories — no raw SQL here.

Usage:
    from app.services.recruiter_analytics_service import RecruiterAnalyticsService

    svc = RecruiterAnalyticsService(
        job_repo=job_repo,
        application_repo=app_repo,
        ats_score_repo=ats_repo,
    )

    dashboard = svc.get_dashboard(recruiter_id="abc123")
    pipeline  = svc.get_pipeline(recruiter_id="abc123")
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class RecruiterDashboard:
    """High-level recruiter dashboard metrics."""
    recruiter_id:         str
    total_jobs:           int = 0
    active_jobs:          int = 0
    total_applications:   int = 0
    total_hired:          int = 0
    avg_score:            float = 0.0
    pipeline_funnel:      dict = field(default_factory=dict)
    top_jobs:             list = field(default_factory=list)
    score_distribution:   dict = field(default_factory=dict)
    skills_demand:        list = field(default_factory=list)


class RecruiterAnalyticsService:
    """
    Computes analytics for a recruiter's hiring pipeline.
    """

    def __init__(self, job_repo, application_repo, ats_score_repo):
        self._job_repo  = job_repo
        self._app_repo  = application_repo
        self._ats_repo  = ats_score_repo

    def get_dashboard(self, recruiter_id: str) -> RecruiterDashboard:
        """
        Return full dashboard metrics for a recruiter.

        Args:
            recruiter_id: Recruiter UUID.

        Returns:
            RecruiterDashboard
        """
        try:
            return self._build_dashboard(recruiter_id)
        except Exception as exc:
            logger.exception("Dashboard computation failed for recruiter=%s", recruiter_id)
            return RecruiterDashboard(recruiter_id=recruiter_id)

    def get_pipeline(self, recruiter_id: str) -> dict:
        """
        Return pipeline funnel data: counts per ApplicationStage.

        Returns:
            {stage_name: count, ...}
        """
        try:
            jobs = self._job_repo.list_by_recruiter(recruiter_id, include_closed=True, with_count=False, page=None, limit=None,)
            if not jobs:
                return {}

            from collections import Counter
            stage_counts: Counter = Counter()
            for job in jobs:
                counts = self._app_repo.count_by_stage(job_id=job.id)
                for stage, count in counts.items():
                    stage_counts[stage] += count

            return dict(stage_counts)
        except Exception as exc:
            logger.warning("Pipeline computation failed: %s", exc)
            return {}

    def get_job_performance(
        self,
        recruiter_id: str,
        job_id: str,
    ) -> dict:
        """
        Return performance metrics for a single job posting.

        Returns:
            {applicant_count, avg_score, stage_breakdown, top_skills_matched}
        """
        try:
            job = self._job_repo.get_by_id(job_id)
            if not job or job.recruiter_id != recruiter_id:
                return {}

            stage_counts = self._app_repo.count_by_stage(job_id=job_id)
            top_scores   = self._ats_repo.get_top_for_job(job_id=job_id, top_n=50)

            avg_score = 0.0
            if top_scores:
                avg_score = round(sum(s.final_score for s in top_scores) / len(top_scores), 3)

            return {
                "job_id":          job_id,
                "title":           job.title,
                "applicant_count": job.applicant_count,
                "stage_breakdown": stage_counts,
                "avg_ats_score":   avg_score,
                "quality_score":   job.quality_score,
            }
        except Exception as exc:
            logger.warning("Job performance failed: %s", exc)
            return {}

    # ── Internal ──────────────────────────────────────────────────────────────

    def _build_dashboard(self, recruiter_id: str) -> RecruiterDashboard:
        from app.models.enums import JobStatus, ApplicationStage
        from collections import Counter

        # ── Jobs ──────────────────────────────────────────────────────────────
        all_jobs  = self._job_repo.list_by_recruiter(recruiter_id, include_closed=True , with_count=False, page=None, limit=None,)
        active_jobs = [j for j in all_jobs if j.status == JobStatus.ACTIVE]

        # ── Applications ──────────────────────────────────────────────────────
        total_applications = 0
        total_hired        = 0
        pipeline_funnel: Counter = Counter()

        for job in all_jobs:
            counts = self._app_repo.count_by_stage(job_id=job.id)
            for stage, count in counts.items():
                pipeline_funnel[stage] += count
                total_applications += count
                if stage == ApplicationStage.HIRED:
                    total_hired += count

        # ── ATS scores ────────────────────────────────────────────────────────
        all_scores = []
        score_dist = {"excellent": 0, "good": 0, "fair": 0, "weak": 0}
        for job in all_jobs:
            job_scores, _ = self._ats_repo.list_by_job(job_id=job.id, page=1, limit=200)
            for s in job_scores:
                all_scores.append(s.final_score)
                label = s.score_label
                if label in score_dist:
                    score_dist[label] += 1

        avg_score = 0.0
        if all_scores:
            avg_score = round(sum(all_scores) / len(all_scores), 3)

        # ── Top jobs by applicant count ───────────────────────────────────────
        top_jobs = sorted(
            all_jobs,
            key=lambda j: j.applicant_count,
            reverse=True
        )[:5]
        top_jobs_data = []
        for j in top_jobs:
            # Calculate avg score for this job specifically for the ranking
            job_scores, _ = self._ats_repo.list_by_job(job_id=j.id, page=1, limit=100)
            avg = sum(s.final_score for s in job_scores) / len(job_scores) if job_scores else 0.0
            top_jobs_data.append({
                "job_id":          j.id,
                "title":           j.title,
                "applicant_count": j.applicant_count,
                "status":          j.status,
                "avg_score":       round(avg, 3),
            })

        # ── Skills demand ─────────────────────────────────────────────────────
        skill_demand: Counter = Counter()
        for job in active_jobs:
            for skill in job.required_skills_list:
                skill_demand[skill.lower()] += 1
        skills_demand_list = [
            {"skill": s, "count": c}
            for s, c in skill_demand.most_common(15)
        ]

        return RecruiterDashboard(
            recruiter_id=recruiter_id,
            total_jobs=len(all_jobs),
            active_jobs=len(active_jobs),
            total_applications=total_applications,
            total_hired=total_hired,
            avg_score=avg_score,
            pipeline_funnel=dict(pipeline_funnel),
            top_jobs=top_jobs_data,
            score_distribution=score_dist,
            skills_demand=skills_demand_list,
        )