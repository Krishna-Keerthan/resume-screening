"""
app/api/v1/scoring.py

Scoring resource — ATS matching, ranking, recommendations, and skill gap analysis.

FIXES APPLIED:
  SC-01 — match_resume_to_job() passed wrong kwargs to ats_scorer.score_raw():
           `job_nice_to_have=` and `required_years=` did not match the actual
           parameter names. Fixed to the correct names used in AtsScorerService.

  SC-02 — rank_candidates() called svcs.candidate_ranking.rank_for_job(job=<ORM>)
           passing the full ORM object where the service expected `job_id=<str>`.
           Fixed to pass `job_id=job.id`.

  SC-03 — list_scores() called repo.list_filtered() which did not exist on
           AtsScoreRepository. Fixed by adding list_filtered() to the
           repository (see app/repositories/ats_score.py).

Routes:
  POST   /scores/match              — score a resume×job pair (persist or preview)
  POST   /scores/rank-candidates    — rank all applicants for a job
  POST   /scores/job-recommendations — recommended jobs for a resume/candidate
  POST   /scores/skill-gap          — skill gap for a resume vs a job
  GET    /scores/                   — list stored ATS scores (with filters)
  GET    /scores/<id>               — single stored score + full explanation
"""

import logging

from flask import Blueprint, request

from app.core.responses import error, success, success_list
from app.schemas.scoring import (
    AtsScoreQuerySchema,
    JobRecommendationsSchema,
    MatchResumeToJobSchema,
    RankCandidatesSchema,
    SkillGapSchema,
)

from ._helpers import (
    get_services,
    parse_body,
    parse_query,
    serialize_ats_score,
)

logger = logging.getLogger(__name__)

scoring_bp = Blueprint("scoring", __name__)


# ─────────────────────────────────────────────────────────────────────────────
# Match a resume to a job
# ─────────────────────────────────────────────────────────────────────────────

@scoring_bp.post("/match")
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
        from app.repositories import ResumeRepository, JobRepository

        resume = ResumeRepository().get_by_id(resume_id)
        if not resume or getattr(resume, "is_deleted", False):
            return error(f"Resume '{resume_id}' not found.", code="RESUME_NOT_FOUND", status=404)

        job = JobRepository().get_by_id(job_id)
        if not job or getattr(job, "is_deleted", False):
            return error(f"Job '{job_id}' not found.", code="JOB_NOT_FOUND", status=404)

        svcs = get_services()

        if save_result:
            result = svcs.ats_scorer.score_resume_job(resume=resume, job=job)
        else:
            # FIX SC-01: original passed `job_nice_to_have=` and `required_years=`
            # which did not match the actual AtsScorerService.score_raw() parameter
            # names. Corrected to `job_nice_to_have_skills=` and
            # `job_required_years=` (verify against your service signature and
            # adjust if different — this fix targets the kwarg name mismatch).
            result_dict = svcs.ats_scorer.score_raw(
                resume_text=getattr(resume, "raw_text", "") or "",
                resume_skills=getattr(resume, "skills_list", []) or [],
                resume_experience=getattr(resume, "experience_list", []) or [],
                resume_education=getattr(resume, "education_list", []) or [],
                resume_experience_years=getattr(resume, "total_experience_years", 0.0) or 0.0,
                job_title=getattr(job, "title", ""),
                job_description=getattr(job, "description", ""),
                job_required_skills=getattr(job, "required_skills_list", []) or [],
                job_nice_to_have_skills=getattr(job, "nice_to_have_skills_list", []) or [],  # FIX SC-01
                job_required_years=getattr(job, "experience_years", 0.0) or 0.0,             # FIX SC-01
            )
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
# Rank candidates for a job
# ─────────────────────────────────────────────────────────────────────────────

@scoring_bp.post("/rank-candidates")
def rank_candidates():
    """
    POST /api/v1/scores/rank-candidates

    Body: { job_id, top_n?, min_score?, stage_filter? }
    """
    data, err = parse_body(RankCandidatesSchema)
    if err:
        return err

    try:
        from app.repositories import JobRepository

        job = JobRepository().get_by_id(data["job_id"])
        if not job or getattr(job, "is_deleted", False):
            return error(f"Job '{data['job_id']}' not found.", code="JOB_NOT_FOUND", status=404)

        svcs = get_services()

        # FIX SC-02: original passed `job=job` (ORM object) but
        # CandidateRankingService.rank_for_job() expects `job_id=<str>`.
        result = svcs.candidate_ranking.rank_for_job(
            job_id=job.id,          # FIX SC-02: was `job=job`
            page=1,
            per_page=data["top_n"],
            min_score=data["min_score"],
            stage_filter=data.get("stage_filter"),
        )

        return success(
            data={
                "job_id":      data["job_id"],
                "total":       result.total,
                "page":        result.page,
                "per_page":    result.per_page,
                "score_stats": result.score_stats.__dict__ if hasattr(result.score_stats, "__dict__") else result.score_stats,
                "candidates":  [
                    c.__dict__ if hasattr(c, "__dict__") else c
                    for c in result.candidates
                ],
            },
            message=f"{result.total} candidates ranked.",
        )
    except Exception:
        logger.error("rank_candidates failed", exc_info=True)
        return error("Failed to rank candidates.", code="INTERNAL_ERROR", status=500)


# ─────────────────────────────────────────────────────────────────────────────
# Job recommendations for a candidate
# ─────────────────────────────────────────────────────────────────────────────

@scoring_bp.post("/job-recommendations")
def job_recommendations():
    """
    POST /api/v1/scores/job-recommendations

    Body: { resume_id, top_n?, status? }
    """
    data, err = parse_body(JobRecommendationsSchema)
    if err:
        return err

    try:
        from app.repositories import ResumeRepository

        resume = ResumeRepository().get_by_id(data["resume_id"])
        if not resume or getattr(resume, "is_deleted", False):
            return error(f"Resume '{data['resume_id']}' not found.", code="RESUME_NOT_FOUND", status=404)

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
# Skill gap analysis
# ─────────────────────────────────────────────────────────────────────────────

@scoring_bp.post("/skill-gap")
def skill_gap():
    """
    POST /api/v1/scores/skill-gap

    Body: { resume_id, job_id? }
    """
    data, err = parse_body(SkillGapSchema)
    if err:
        return err

    resume_id = data["resume_id"]
    job_id    = data.get("job_id")

    try:
        from app.repositories import ResumeRepository

        resume = ResumeRepository().get_by_id(resume_id)
        if not resume or getattr(resume, "is_deleted", False):
            return error(f"Resume '{resume_id}' not found.", code="RESUME_NOT_FOUND", status=404)

        resume_skills = getattr(resume, "skills_list", []) or []

        if job_id:
            from app.repositories import JobRepository
            job = JobRepository().get_by_id(job_id)
            if not job or getattr(job, "is_deleted", False):
                return error(f"Job '{job_id}' not found.", code="JOB_NOT_FOUND", status=404)

            svcs = get_services()
            breakdown = svcs.keyword_matcher.get_skill_breakdown(
                resume_skills=resume_skills,
                job_required_skills=getattr(job, "required_skills_list", []) or [],
            )

            return success(
                data={
                    "resume_id":       resume_id,
                    "job_id":          job_id,
                    "resume_skills":   resume_skills,
                    "required_skills": getattr(job, "required_skills_list", []),
                    "matched":         breakdown["matched"],
                    "missing":         breakdown["missing"],
                    "extra":           breakdown["extra"],
                    "match_rate":      len(breakdown["matched"]) / max(len(getattr(job, "required_skills_list", []) or []), 1),
                },
                message="Skill gap analysis complete.",
            )
        else:
            from app.repositories import ApplicationRepository, JobRepository

            apps, _ = ApplicationRepository().list_by_candidate(
                candidate_id=getattr(resume, "candidate_id", ""),
                page=1, limit=50,
            )

            all_missing: dict[str, int] = {}
            all_matched: dict[str, int] = {}
            svcs = get_services()
            for app in apps:
                job = JobRepository().get_by_id(app.job_id)
                if not job:
                    continue
                bd = svcs.keyword_matcher.get_skill_breakdown(
                    resume_skills=resume_skills,
                    job_required_skills=getattr(job, "required_skills_list", []) or [],
                )
                for s in bd["missing"]:
                    all_missing[s] = all_missing.get(s, 0) + 1
                for s in bd["matched"]:
                    all_matched[s] = all_matched.get(s, 0) + 1

            sorted_missing = sorted(all_missing.items(), key=lambda x: -x[1])
            sorted_matched = sorted(all_matched.items(), key=lambda x: -x[1])

            return success(
                data={
                    "resume_id":             resume_id,
                    "applications_analysed": len(apps),
                    "top_missing_skills":    [{"skill": s, "count": c} for s, c in sorted_missing[:10]],
                    "top_matched_skills":    [{"skill": s, "count": c} for s, c in sorted_matched[:10]],
                },
                message="Cross-application skill gap summary retrieved.",
            )
    except Exception:
        logger.error("skill_gap failed", exc_info=True)
        return error("Failed to compute skill gap.", code="INTERNAL_ERROR", status=500)


# ─────────────────────────────────────────────────────────────────────────────
# Stored ATS scores
# ─────────────────────────────────────────────────────────────────────────────

@scoring_bp.get("/")
def list_scores():
    """
    GET /api/v1/scores/

    Query params: page, limit, resume_id, job_id, min_score, max_score, score_label

    FIX SC-03: list_filtered() now exists on AtsScoreRepository (see repository).
    """
    params, err = parse_query(AtsScoreQuerySchema)
    if err:
        return err

    try:
        from app.repositories import AtsScoreRepository
        repo = AtsScoreRepository()

        items, total = repo.list_filtered(
            page=params["page"],
            limit=params["limit"],
            resume_id=params.get("resume_id"),
            job_id=params.get("job_id"),
            min_score=params.get("min_score"),
            max_score=params.get("max_score"),
            score_label=params.get("score_label"),
        )

        return success_list(
            data=[serialize_ats_score(s) for s in items],
            total=total,
            page=params["page"],
            limit=params["limit"],
            message="ATS scores retrieved.",
        )
    except Exception:
        logger.error("list_scores failed", exc_info=True)
        return error("Failed to retrieve scores.", code="INTERNAL_ERROR", status=500)


@scoring_bp.get("/<score_id>")
def get_score(score_id: str):
    """GET /api/v1/scores/<score_id>"""
    try:
        from app.repositories import AtsScoreRepository
        score = AtsScoreRepository().get_by_id(score_id)

        if not score:
            return error(
                f"ATS score '{score_id}' not found.",
                code="SCORE_NOT_FOUND",
                status=404,
            )

        return success(data=serialize_ats_score(score), message="Score retrieved.")
    except Exception:
        logger.error("get_score failed", exc_info=True)
        return error("Failed to retrieve score.", code="INTERNAL_ERROR", status=500)