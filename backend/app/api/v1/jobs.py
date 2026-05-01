"""
app/api/v1/jobs.py

Jobs resource — job posting management, smart AI enhancement, candidate ranking.

Routes:
  GET    /jobs/                      — paginated list of active jobs
  POST   /jobs/                      — create job posting
  GET    /jobs/<id>                  — get single job
  PATCH  /jobs/<id>                  — update job fields
  DELETE /jobs/<id>                  — soft-delete job
  POST   /jobs/<id>/enhance          — AI-enhance description (Groq)
  GET    /jobs/<id>/candidates        — ranked candidate list for job
  GET    /jobs/<id>/skill-gaps        — aggregate skill gap summary
  GET    /jobs/<id>/performance       — job performance metrics
"""

import logging
import uuid

from flask import Blueprint, request

from app.core.security import require_auth

from app.core.responses import created, error, no_content, success, success_list
from app.schemas.job import CreateJobSchema, JobQuerySchema, UpdateJobSchema

from ._helpers import (
    get_services,
    parse_body,
    parse_query,
    serialize_job,
)

logger = logging.getLogger(__name__)

jobs_bp = Blueprint("jobs", __name__)


# ─────────────────────────────────────────────────────────────────────────────
# List + Create
# ─────────────────────────────────────────────────────────────────────────────

@jobs_bp.get("")
def list_jobs():
    """
    GET /api/v1/jobs/

    Query params: page, limit, search, status, job_type, location,
                  recruiter_id, min_experience, max_experience
    """
    params, err = parse_query(JobQuerySchema)
    if err:
        return err

    try:
        from app.repositories import JobRepository
        repo = JobRepository()

        # If a status is given use generic list; otherwise list_active
        if params.get("status"):
            items, total = repo.list_all(
                page=params["page"],
                limit=params["limit"],
                status=params["status"],
                search=params.get("search"),
                location=params.get("location"),
                job_type=params.get("job_type"),
                recruiter_id=params.get("recruiter_id"),
                min_experience=params.get("min_experience"),
                max_experience=params.get("max_experience"),
            )
        else:
            items, total = repo.list_active(
                page=params["page"],
                limit=params["limit"],
                search=params.get("search"),
                location=params.get("location"),
                job_type=params.get("job_type"),
                recruiter_id=params.get("recruiter_id"),
                min_experience=params.get("min_experience"),
                max_experience=params.get("max_experience"),
            )

        return success_list(
            data=[serialize_job(j) for j in items],
            total=total,
            page=params["page"],
            limit=params["limit"],
            message="Jobs retrieved.",
        )
    except Exception:
        logger.error("list_jobs failed", exc_info=True)
        return error("Failed to retrieve jobs.", code="INTERNAL_ERROR", status=500)


@jobs_bp.post("")
def create_job():
    """
    POST /api/v1/jobs/

    Body: { title, company, description, required_skills?, ... }

    Automatically triggers smart enhancement if recruiter_id is provided.
    """
    data, err = parse_body(CreateJobSchema)
    if err:
        return err

    try:
        from app.models.job import Job
        from app.models.enums import JobStatus, JobType
        from app.repositories import JobRepository

        job = Job()
        job.id                  = str(uuid.uuid4())
        job.recruiter_id        = data.get("recruiter_id")
        job.title               = data["title"]
        job.company             = data["company"]
        job.description         = data["description"]
        job.experience_years    = data.get("experience_years", 0.0)
        job.location            = data.get("location", "Remote")
        raw_type = data.get("job_type", JobType.FULL_TIME.value)
        job.job_type = raw_type.value if hasattr(raw_type, "value") else raw_type
        raw_status = data.get("status", JobStatus.ACTIVE.value)
        job.status = raw_status.value if hasattr(raw_status, "value") else raw_status
        job.salary_min          = data.get("salary_min")
        job.salary_max          = data.get("salary_max")
        job.salary_currency     = data.get("salary_currency", "USD")
        job.required_skills_list     = data.get("required_skills", [])
        job.nice_to_have_skills_list = data.get("nice_to_have_skills", [])
        job.responsibilities_list    = data.get("responsibilities", [])
        job.applicant_count     = 0

        repo = JobRepository()
        repo.save(job)

        # ── Optional: run smart enhancement on creation ───────────────────────
        try:
            svcs   = get_services()
            result = svcs.smart_job_posting.enhance(job, use_llm=bool(
                svcs.groq.available
            ))
            logger.info("Job created with smart enhancement", extra={"job_id": job.id})
        except Exception:
            logger.warning("Smart enhancement skipped on job creation", exc_info=True)

        logger.info("Job created", extra={"job_id": job.id})
        return created(data=serialize_job(job), message="Job posting created.")
    except Exception:
        logger.error("create_job failed", exc_info=True)
        return error("Failed to create job.", code="INTERNAL_ERROR", status=500)


# ─────────────────────────────────────────────────────────────────────────────
# Single resource
# ─────────────────────────────────────────────────────────────────────────────

@jobs_bp.get("/<job_id>")
def get_job(job_id: str):
    """GET /api/v1/jobs/<job_id>"""
    try:
        from app.repositories import JobRepository
        job = JobRepository().get_by_id(job_id)

        if not job or getattr(job, "is_deleted", False):
            return error(f"Job '{job_id}' not found.", code="JOB_NOT_FOUND", status=404)

        return success(data=serialize_job(job), message="Job retrieved.")
    except Exception:
        logger.error("get_job failed", exc_info=True)
        return error("Failed to retrieve job.", code="INTERNAL_ERROR", status=500)


@jobs_bp.patch("/<job_id>")
def update_job(job_id: str):
    """PATCH /api/v1/jobs/<job_id>"""
    data, err = parse_body(UpdateJobSchema)
    if err:
        return err

    try:
        from app.repositories import JobRepository
        repo = JobRepository()
        job  = repo.get_by_id(job_id)

        if not job or getattr(job, "is_deleted", False):
            return error(f"Job '{job_id}' not found.", code="JOB_NOT_FOUND", status=404)

        _SCALAR = (
            "title", "company", "description", "experience_years",
            "location", "job_type", "status",
            "salary_min", "salary_max", "salary_currency",
        )
        for field in _SCALAR:
            if field in data:
                setattr(job, field, data[field])

        if "required_skills" in data:
            job.required_skills_list = data["required_skills"]
        if "nice_to_have_skills" in data:
            job.nice_to_have_skills_list = data["nice_to_have_skills"]
        if "responsibilities" in data:
            job.responsibilities_list = data["responsibilities"]

        repo.save(job)
        logger.info("Job updated", extra={"job_id": job_id})
        return success(data=serialize_job(job), message="Job updated.")
    except Exception:
        logger.error("update_job failed", exc_info=True)
        return error("Failed to update job.", code="INTERNAL_ERROR", status=500)


@jobs_bp.delete("/<job_id>")
def delete_job(job_id: str):
    """DELETE /api/v1/jobs/<job_id> — soft-delete."""
    try:
        from app.repositories import JobRepository
        repo = JobRepository()
        job  = repo.get_by_id(job_id)

        if not job or getattr(job, "is_deleted", False):
            return error(f"Job '{job_id}' not found.", code="JOB_NOT_FOUND", status=404)

        repo.soft_delete(job)
        logger.info("Job deleted", extra={"job_id": job_id})
        return no_content()
    except Exception:
        logger.error("delete_job failed", exc_info=True)
        return error("Failed to delete job.", code="INTERNAL_ERROR", status=500)


# ─────────────────────────────────────────────────────────────────────────────
# AI Enhancement
# ─────────────────────────────────────────────────────────────────────────────

@jobs_bp.post("/<job_id>/enhance")
def enhance_job(job_id: str):
    """
    POST /api/v1/jobs/<job_id>/enhance

    Runs SmartJobPostingService to:
      1. Parse description for skills, experience, location
      2. Optionally call Groq for narrative improvements
      3. Compute quality + completeness scores
      4. Check for duplicate postings
      5. Persist enhancements to the Job record

    Body (optional): { use_llm: true }
    """
    body    = request.get_json(silent=True) or {}
    use_llm = bool(body.get("use_llm", True))

    try:
        from app.repositories import JobRepository
        repo = JobRepository()
        job  = repo.get_by_id(job_id)

        if not job or getattr(job, "is_deleted", False):
            return error(f"Job '{job_id}' not found.", code="JOB_NOT_FOUND", status=404)

        svcs   = get_services()
        result = svcs.smart_job_posting.enhance(job, use_llm=use_llm and svcs.groq.available)

        return success(
            data={
                "job_id":              result.job_id,
                "required_skills":     result.required_skills,
                "nice_to_have_skills": result.nice_to_have_skills,
                "responsibilities":    result.responsibilities,
                "enhanced_description":result.enhanced_description,
                "quality_score":       result.quality_score,
                "completeness_score":  result.completeness_score,
                "suggestions":         result.suggestions,
                "duplicate_ids":       result.duplicate_ids,
                "llm_enhanced":        result.llm_enhanced,
                "job":                 serialize_job(job),
            },
            message="Job enhanced successfully." if result.llm_enhanced else
                    "Job parsed and scored (Groq unavailable — rule-based only).",
        )
    except Exception:
        logger.error("enhance_job failed", exc_info=True)
        return error("Failed to enhance job.", code="INTERNAL_ERROR", status=500)


# ─────────────────────────────────────────────────────────────────────────────
# Candidate ranking sub-resource
# ─────────────────────────────────────────────────────────────────────────────

@jobs_bp.get("/<job_id>/candidates")
def rank_candidates(job_id: str):
    """
    GET /api/v1/jobs/<job_id>/candidates

    Returns ATS-ranked applicants for this job.

    Query params:
      page         — page number (default 1)
      limit        — results per page (default 20, max 50)
      min_score    — filter by minimum final score (0.0–1.0)
      stage        — filter by application stage
    """
    page      = int(request.args.get("page", 1))
    limit     = min(int(request.args.get("limit", 20)), 50)
    min_score = float(request.args.get("min_score", 0.0))
    stage     = request.args.get("stage")

    try:
        from app.repositories import JobRepository
        job = JobRepository().get_by_id(job_id)

        if not job or getattr(job, "is_deleted", False):
            return error(f"Job '{job_id}' not found.", code="JOB_NOT_FOUND", status=404)

        svcs   = get_services()
        result = svcs.candidate_ranking.rank_for_job(
            job_id=job_id,
            page=page,
            per_page=limit,
            min_score=min_score,
            stage_filter=stage,
        )

        candidates = []
        for c in result.candidates:
            candidates.append(
                c.__dict__ if hasattr(c, "__dict__") else c
            )

        return success_list(
            data=candidates,
            total=result.total,
            page=result.page,
            limit=result.per_page,
            message=f"{result.total} candidates ranked.",
        )
    except Exception:
        logger.error("rank_candidates failed", exc_info=True)
        return error("Failed to rank candidates.", code="INTERNAL_ERROR", status=500)


@jobs_bp.get("/<job_id>/skill-gaps")
def get_skill_gaps(job_id: str):
    """
    GET /api/v1/jobs/<job_id>/skill-gaps

    Aggregate skill gap summary across all applicants:
    most common missing skills, most common matched skills, avg match rate.
    """
    try:
        from app.repositories import JobRepository
        job = JobRepository().get_by_id(job_id)

        if not job or getattr(job, "is_deleted", False):
            return error(f"Job '{job_id}' not found.", code="JOB_NOT_FOUND", status=404)

        svcs   = get_services()
        gaps   = svcs.candidate_ranking.get_skill_gap_summary(job_id)
        return success(
            data=gaps.__dict__ if hasattr(gaps, "__dict__") else gaps,
            message="Skill gap summary retrieved.",
        )
    except Exception:
        logger.error("get_skill_gaps failed", exc_info=True)
        return error("Failed to retrieve skill gaps.", code="INTERNAL_ERROR", status=500)


# jobs.py — replace lines ~365–390

@jobs_bp.get("/<job_id>/performance")
@require_auth("recruiter")                      # ← add auth guard too
def get_job_performance(job_id: str):
    """
    GET /api/v1/jobs/<job_id>/performance
    Returns applicant_count, avg_score, stage_breakdown, top_skills_matched.
    """
    from flask import g
    try:
        from app.repositories import JobRepository
        job = JobRepository().get_by_id(job_id)

        if not job or getattr(job, "is_deleted", False):
            return error(f"Job '{job_id}' not found.", code="JOB_NOT_FOUND", status=404)

        svcs = get_services()
        perf = svcs.recruiter_analytics.get_job_performance(
            recruiter_id=g.jwt_user_id,             # ← pass the authenticated recruiter
            job_id=job_id,
        )

        if not perf:                            # service returns {} if ownership fails
            return error("Access denied or job not found.", code="FORBIDDEN", status=403)

        return success(
            data=perf,
            message="Job performance metrics retrieved.",
        )
    except Exception:
        logger.error("get_job_performance failed", exc_info=True)
        return error("Failed to retrieve job performance.", code="INTERNAL_ERROR", status=500)