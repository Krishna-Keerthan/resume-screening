"""
app/api/v1/analytics.py

Analytics resource — aggregated platform metrics for recruiter dashboards.

Routes:
  GET  /analytics/dashboard         — full recruiter dashboard (pass recruiter_id)
  GET  /analytics/pipeline          — pipeline funnel counts
  GET  /analytics/score-distribution — score label breakdown across all jobs
  GET  /analytics/skills-demand      — most in-demand skills across active jobs
  GET  /analytics/top-jobs           — top N jobs by applicant volume
"""

import logging

from flask import Blueprint, request

from app.core.responses import error, success

from ._helpers import get_services

logger = logging.getLogger(__name__)

analytics_bp = Blueprint("analytics", __name__)


@analytics_bp.get("/dashboard")
def analytics_dashboard():
    """
    GET /api/v1/analytics/dashboard?recruiter_id=<id>

    Returns the full RecruiterDashboard:
      - total_jobs, active_jobs
      - total_applications, total_hired
      - avg_score
      - pipeline_funnel  (stage → count)
      - top_jobs         (sorted by applicant_count)
      - score_distribution (excellent/good/fair/weak counts)
      - skills_demand    (most required skills)
    """
    recruiter_id = request.args.get("recruiter_id")
    if not recruiter_id:
        return error(
            "recruiter_id query parameter is required.",
            code="MISSING_PARAM",
            status=400,
        )

    try:
        from app.repositories import RecruiterRepository
        if not RecruiterRepository().get_by_id(recruiter_id):
            return error(
                f"Recruiter '{recruiter_id}' not found.",
                code="RECRUITER_NOT_FOUND",
                status=404,
            )

        svcs      = get_services()
        dashboard = svcs.recruiter_analytics.get_dashboard(recruiter_id)

        # Serialise dataclass → plain dict
        def _to_dict(obj):
            if obj is None:
                return None
            if hasattr(obj, "__dict__"):
                return {k: _to_dict(v) for k, v in obj.__dict__.items() if not k.startswith("_")}
            if isinstance(obj, list):
                return [_to_dict(i) for i in obj]
            return obj

        return success(data=_to_dict(dashboard), message="Dashboard retrieved.")
    except Exception:
        logger.error("analytics_dashboard failed", exc_info=True)
        return error("Failed to retrieve dashboard.", code="INTERNAL_ERROR", status=500)


@analytics_bp.get("/pipeline")
def analytics_pipeline():
    """
    GET /api/v1/analytics/pipeline?recruiter_id=<id>

    Returns application counts per stage for a recruiter's jobs.
    """
    recruiter_id = request.args.get("recruiter_id")
    if not recruiter_id:
        return error("recruiter_id query parameter is required.", code="MISSING_PARAM", status=400)

    try:
        svcs     = get_services()
        pipeline = svcs.recruiter_analytics.get_pipeline(recruiter_id)
        return success(
            data=pipeline.__dict__ if hasattr(pipeline, "__dict__") else pipeline,
            message="Pipeline breakdown retrieved.",
        )
    except Exception:
        logger.error("analytics_pipeline failed", exc_info=True)
        return error("Failed to retrieve pipeline.", code="INTERNAL_ERROR", status=500)


@analytics_bp.get("/score-distribution")
def analytics_score_distribution():
    """
    GET /api/v1/analytics/score-distribution?recruiter_id=<id>

    Returns how many candidates fall into each score band:
    excellent / good / fair / weak.
    """
    recruiter_id = request.args.get("recruiter_id")
    if not recruiter_id:
        return error("recruiter_id query parameter is required.", code="MISSING_PARAM", status=400)

    try:
        svcs      = get_services()
        dashboard = svcs.recruiter_analytics.get_dashboard(recruiter_id)
        dist      = getattr(dashboard, "score_distribution", {})
        return success(
            data=dist.__dict__ if hasattr(dist, "__dict__") else dist,
            message="Score distribution retrieved.",
        )
    except Exception:
        logger.error("analytics_score_distribution failed", exc_info=True)
        return error("Failed to retrieve score distribution.", code="INTERNAL_ERROR", status=500)


@analytics_bp.get("/skills-demand")
def analytics_skills_demand():
    """
    GET /api/v1/analytics/skills-demand?recruiter_id=<id>&top_n=15

    Returns the most frequently required skills across a recruiter's active jobs.
    """
    recruiter_id = request.args.get("recruiter_id")
    top_n        = int(request.args.get("top_n", 15))
    top_n        = min(max(top_n, 1), 50)

    if not recruiter_id:
        return error("recruiter_id query parameter is required.", code="MISSING_PARAM", status=400)

    try:
        svcs      = get_services()
        dashboard = svcs.recruiter_analytics.get_dashboard(recruiter_id)
        demand    = getattr(dashboard, "skills_demand", []) or []

        # Slice to top_n
        if isinstance(demand, list):
            demand = demand[:top_n]
        elif isinstance(demand, dict):
            demand = sorted(demand.items(), key=lambda x: -x[1])[:top_n]
            demand = [{"skill": k, "count": v} for k, v in demand]

        return success(
            data={"recruiter_id": recruiter_id, "skills": demand},
            message="Skills demand retrieved.",
        )
    except Exception:
        logger.error("analytics_skills_demand failed", exc_info=True)
        return error("Failed to retrieve skills demand.", code="INTERNAL_ERROR", status=500)


@analytics_bp.get("/top-jobs")
def analytics_top_jobs():
    """
    GET /api/v1/analytics/top-jobs?recruiter_id=<id>&top_n=5

    Returns the recruiter's jobs sorted by applicant volume.
    """
    recruiter_id = request.args.get("recruiter_id")
    top_n        = int(request.args.get("top_n", 5))
    top_n        = min(max(top_n, 1), 20)

    if not recruiter_id:
        return error("recruiter_id query parameter is required.", code="MISSING_PARAM", status=400)

    try:
        svcs      = get_services()
        dashboard = svcs.recruiter_analytics.get_dashboard(recruiter_id)
        top_jobs  = getattr(dashboard, "top_jobs", []) or []

        if isinstance(top_jobs, list):
            top_jobs = top_jobs[:top_n]

        serialised = []
        for j in top_jobs:
            serialised.append(j.__dict__ if hasattr(j, "__dict__") else j)

        return success(
            data={"recruiter_id": recruiter_id, "jobs": serialised},
            message="Top jobs retrieved.",
        )
    except Exception:
        logger.error("analytics_top_jobs failed", exc_info=True)
        return error("Failed to retrieve top jobs.", code="INTERNAL_ERROR", status=500)
