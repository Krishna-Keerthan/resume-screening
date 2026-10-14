"""
app/api/v1/scoring.py

Scoring resource — ATS matching, ranking, recommendations, and skill gap analysis.

Every route needs a token.

Routes:
  POST   /scores/match              — score a resume×job pair (persist or preview)
                                      [candidate: own resume, active job;
                                       recruiter: own job, resume submitted to it]
  POST   /scores/job-recommendations — recommended jobs for a resume       [candidate, own resume]
  GET    /scores/<id>               — single stored score + full explanation
                                      [the resume's candidate, or the job's recruiter]
"""

import logging

from flask import Blueprint

from app.core.responses import error, success
from app.core.extensions import llm_limit
from app.core.security import require_auth
from app.services.ats_scorer import scorer_inputs
from app.schemas.scoring import JobRecommendationsSchema, MatchResumeToJobSchema

from ._helpers import (
    get_owned_resume,
    get_scorable_pair,
    get_services,
    get_viewable_score,
    parse_body,
    serialize_ats_score,
)

logger = logging.getLogger(__name__)

scoring_bp = Blueprint("scoring", __name__)


# ─────────────────────────────────────────────────────────────────────────────
# Match a resume to a job
# ─────────────────────────────────────────────────────────────────────────────

@scoring_bp.post("/match")
@require_auth("candidate", "recruiter")
@llm_limit
def match_resume_to_job():
    """
    POST /api/v1/scores/match

    Compute the full 4-component ATS score for a resume × job pair.

    Body: { resume_id, job_id, save_result? (default true) }
    """
    data, err = parse_body(MatchResumeToJobSchema)
    if err:
        return err

    resume_id   = data["resume_id"]
    job_id      = data["job_id"]
    save_result = data.get("save_result", True)

    try:
        resume, job, err = get_scorable_pair(resume_id, job_id)
        if err:
            return err

        svcs = get_services()

        if save_result:
            result = svcs.ats_scorer.score_resume_job(resume=resume, job=job)
        else:
            result_dict = svcs.ats_scorer.score_raw(**scorer_inputs(resume, job))
            return success(
                data={"resume_id": resume_id, "job_id": job_id, "saved": False, **result_dict},
                message="Score computed (not saved).",
            )

        if result.error:
            return error(f"Scoring failed: {result.error}", code="SCORING_FAILED", status=500)

        return success(
            data={
                "resume_id":             result.resume_id,
                "job_id":                result.job_id,
                "saved":                 True,
                "ats_score_id":          result.ats_score_id,
                "final_score":           result.final_score,
                "score_label":           result.score_label,
                "semantic_score":        result.semantic_score,
                "keyword_score":         result.keyword_score,
                "experience_score":      result.experience_score,
                "section_quality_score": result.section_quality_score,
                "semantic_available":    result.semantic_available,
                "matched_skills":        result.matched_skills,
                "missing_skills":        result.missing_skills,
                "extra_skills":          result.extra_skills,
                "improvement_tips":      result.improvement_tips,
                "summary_text":          result.summary_text,
                "hiring_recommendation": result.hiring_recommendation,
            },
            message="ATS score computed and saved.",
        )
    except Exception:
        logger.error("match_resume_to_job failed", exc_info=True)
        return error("Failed to compute ATS score.", code="INTERNAL_ERROR", status=500)


# ─────────────────────────────────────────────────────────────────────────────
# Job recommendations for a candidate
# ─────────────────────────────────────────────────────────────────────────────

@scoring_bp.post("/job-recommendations")
@require_auth("candidate")
def job_recommendations():
    """
    POST /api/v1/scores/job-recommendations

    Body: { resume_id, top_n?, status? }
    """
    data, err = parse_body(JobRecommendationsSchema)
    if err:
        return err

    try:
        resume, err = get_owned_resume(data["resume_id"])
        if err:
            return err

        parse_status = getattr(getattr(resume, "parse_status", None), "value", None)
        if parse_status and parse_status != "success":
            return error(
                "Resume has not been parsed yet. Upload or re-parse before requesting recommendations.",
                code="RESUME_NOT_PARSED",
                status=422,
            )

        svcs = get_services()
        recs = svcs.job_recommendations.recommend(
            resume=resume,
            top_n=data["top_n"],
        )

        return success(
            data={
                "resume_id":       data["resume_id"],
                "total":           len(recs),
                "recommendations": [
                    r.__dict__ if hasattr(r, "__dict__") else r
                    for r in recs
                ],
            },
            message=f"{len(recs)} job recommendations retrieved.",
        )
    except Exception:
        logger.error("job_recommendations failed", exc_info=True)
        return error("Failed to retrieve job recommendations.", code="INTERNAL_ERROR", status=500)


# ─────────────────────────────────────────────────────────────────────────────
# Stored ATS scores
# ─────────────────────────────────────────────────────────────────────────────

@scoring_bp.get("/<score_id>")
@require_auth("candidate", "recruiter")
def get_score(score_id: str):
    """GET /api/v1/scores/<score_id>"""
    try:
        score, err = get_viewable_score(score_id)
        if err:
            return err

        return success(data=serialize_ats_score(score), message="Score retrieved.")
    except Exception:
        logger.error("get_score failed", exc_info=True)
        return error("Failed to retrieve score.", code="INTERNAL_ERROR", status=500)
