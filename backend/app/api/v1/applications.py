"""
app/api/v1/applications.py

Applications resource — candidate applies to job, recruiters advance stages.

FIXES APPLIED:
  AP-01 — update_application_stage() set the stage via direct attribute
           assignment (`application.stage = new_stage_enum`) instead of
           calling `application.advance_stage(new_stage, actor_id)`.

           Direct assignment:
             • Skips the STAGE_TRANSITIONS guard — any stage jump is accepted,
               even invalid ones (e.g. "applied" → "hired" skipping screening).
             • Never appends to stage_history, so the audit trail is empty.

           Fix: replace direct assignment with application.advance_stage().
           ValueError from invalid transitions is caught and returned as 422.

Routes:
  GET    /applications/              — list (filter by job_id, candidate_id, stage)
  POST   /applications/              — submit application (candidate → job)
  GET    /applications/<id>          — get single application
  PATCH  /applications/<id>/stage    — advance application stage (recruiter action)
  DELETE /applications/<id>          — withdraw application (candidate action)
  POST   /applications/<id>/score    — trigger/refresh ATS score for this application
"""

import logging
import uuid

from flask import Blueprint, request

from app.core.responses import created, error, no_content, success, success_list
from app.schemas.application import (
    ApplicationQuerySchema,
    CreateApplicationSchema,
    UpdateApplicationStageSchema,
)

from ._helpers import (
    get_services,
    parse_body,
    parse_query,
    serialize_application,
    serialize_ats_score,
)

logger = logging.getLogger(__name__)

applications_bp = Blueprint("applications", __name__)


# ─────────────────────────────────────────────────────────────────────────────
# List
# ─────────────────────────────────────────────────────────────────────────────

@applications_bp.get("/")
def list_applications():
    """
    GET /api/v1/applications/

    Query params: page, limit, job_id, candidate_id, stage
    """
    params, err = parse_query(ApplicationQuerySchema)
    if err:
        return err

    job_id       = params.get("job_id")
    candidate_id = params.get("candidate_id")
    stage        = params.get("stage")
    page, limit  = params["page"], params["limit"]

    try:
        from app.repositories import ApplicationRepository
        repo = ApplicationRepository()

        if job_id:
            items, total = repo.list_by_job(
                job_id=job_id, stage=stage, page=page, limit=limit
            )
        elif candidate_id:
            items, total = repo.list_by_candidate(
                candidate_id=candidate_id, stage=stage, page=page, limit=limit
            )
        else:
            logger.warning("list_applications called without job_id or candidate_id filter")
            items, total = repo.list_all(page=page, limit=limit, stage=stage)

        return success_list(
            data=[serialize_application(a) for a in items],
            total=total, page=page, limit=limit,
            message="Applications retrieved.",
        )
    except Exception:
        logger.error("list_applications failed", exc_info=True)
        return error("Failed to retrieve applications.", code="INTERNAL_ERROR", status=500)


# ─────────────────────────────────────────────────────────────────────────────
# Submit application
# ─────────────────────────────────────────────────────────────────────────────

@applications_bp.post("/")
def create_application():
    """
    POST /api/v1/applications/

    Body: { candidate_id, job_id, resume_id, cover_letter? }
    """
    data, err = parse_body(CreateApplicationSchema)
    if err:
        return err

    candidate_id = data["candidate_id"]
    job_id       = data["job_id"]
    resume_id    = data["resume_id"]

    try:
        from app.repositories import (
            ApplicationRepository,
            CandidateRepository,
            JobRepository,
            ResumeRepository,
        )
        from app.models.application import Application
        from app.models.enums import ApplicationStage, JobStatus

        candidate = CandidateRepository().get_by_id(candidate_id)
        if not candidate or getattr(candidate, "is_deleted", False):
            return error(f"Candidate '{candidate_id}' not found.", code="CANDIDATE_NOT_FOUND", status=404)

        job = JobRepository().get_by_id(job_id)
        if not job or getattr(job, "is_deleted", False):
            return error(f"Job '{job_id}' not found.", code="JOB_NOT_FOUND", status=404)

        job_status = getattr(job.status, "value", str(job.status))
        if job_status != JobStatus.ACTIVE.value:
            return error(
                f"Job '{job_id}' is not accepting applications (status: {job_status}).",
                code="JOB_NOT_ACTIVE",
                status=422,
            )

        resume = ResumeRepository().get_by_id(resume_id)
        if not resume or getattr(resume, "is_deleted", False):
            return error(f"Resume '{resume_id}' not found.", code="RESUME_NOT_FOUND", status=404)

        if str(resume.candidate_id) != str(candidate_id):
            return error(
                "Resume does not belong to this candidate.",
                code="RESUME_OWNERSHIP_MISMATCH",
                status=403,
            )

        app_repo = ApplicationRepository()
        if app_repo.application_exists(candidate_id=candidate_id, job_id=job_id):
            return error(
                "Candidate has already applied to this job.",
                code="DUPLICATE_APPLICATION",
                status=409,
            )

        application              = Application()
        application.id           = str(uuid.uuid4())
        application.candidate_id = candidate_id
        application.job_id       = job_id
        application.resume_id    = resume_id
        application.cover_letter = data.get("cover_letter")
        application.stage        = ApplicationStage.APPLIED.value

        app_repo.save(application)

        try:
            job.applicant_count = (getattr(job, "applicant_count", 0) or 0) + 1
            JobRepository().save(job)
        except Exception:
            logger.warning("Failed to increment applicant_count", exc_info=True)

        ats_score_data = None
        try:
            svcs         = get_services()
            score_result = svcs.ats_scorer.score_resume_job(
                resume=resume,
                job=job,
                application_id=application.id,
            )
            if not score_result.error:
                ats_score_data = {
                    "final_score": score_result.final_score,
                    "score_label": score_result.score_label,
                }
        except Exception:
            logger.warning("ATS scoring failed on application create", exc_info=True)

        improvement_plan_data = None
        if ats_score_data and ats_score_data.get("final_score", 1.0) < 0.65:
            try:
                plan_result = svcs.groq.generate_improvement_plan(
                    job_title=job.title,
                    final_score=ats_score_data["final_score"],
                    missing_skills=score_result.missing_skills if not score_result.error else [],
                    matched_skills=score_result.matched_skills if not score_result.error else [],
                    experience_years=getattr(resume, "total_experience_years", 0.0),
                    required_years=getattr(job, "experience_years", 0.0),
                )
                if plan_result.get("plan"):
                    import json
                    application.improvement_plan = json.dumps(plan_result["plan"])
                    app_repo.save(application)
            except Exception:
                logger.warning("Improvement plan generation failed", exc_info=True)

        resp_data = serialize_application(application)
        if ats_score_data:
            resp_data["ats_score"] = ats_score_data

        logger.info(
            "Application created",
            extra={"application_id": application.id, "job_id": job_id, "candidate_id": candidate_id},
        )
        return created(data=resp_data, message="Application submitted successfully.")
    except Exception:
        logger.error("create_application failed", exc_info=True)
        return error("Failed to submit application.", code="INTERNAL_ERROR", status=500)


# ─────────────────────────────────────────────────────────────────────────────
# Single resource
# ─────────────────────────────────────────────────────────────────────────────

@applications_bp.get("/<application_id>")
def get_application(application_id: str):
    """GET /api/v1/applications/<application_id>"""
    try:
        from app.repositories import ApplicationRepository, AtsScoreRepository
        application = ApplicationRepository().get_by_id(application_id)

        if not application:
            return error(
                f"Application '{application_id}' not found.",
                code="APPLICATION_NOT_FOUND",
                status=404,
            )

        data = serialize_application(application)

        try:
            score = AtsScoreRepository().get_by_resume_and_job(
                resume_id=application.resume_id,
                job_id=application.job_id,
            )
            if score:
                data["ats_score"] = serialize_ats_score(score)
        except Exception:
            pass

        return success(data=data, message="Application retrieved.")
    except Exception:
        logger.error("get_application failed", exc_info=True)
        return error("Failed to retrieve application.", code="INTERNAL_ERROR", status=500)


# ─────────────────────────────────────────────────────────────────────────────
# Stage transition
# ─────────────────────────────────────────────────────────────────────────────

@applications_bp.patch("/<application_id>/stage")
def update_application_stage(application_id: str):
    """
    PATCH /api/v1/applications/<application_id>/stage

    Advance or move the application to a new recruitment stage.

    Body: { stage, recruiter_notes?, rejection_reason?, actor_id? }
    Valid stages: applied → screening → interview → offer → hired | rejected

    FIX AP-01: The original implementation set the stage via direct attribute
    assignment (`application.stage = new_stage_enum`). This bypassed
    Application.advance_stage() completely, which means:
      1. STAGE_TRANSITIONS guard was never checked — any stage jump was
         silently accepted (e.g. "applied" → "hired").
      2. stage_history was never updated — the audit trail was always empty.

    Fixed: call application.advance_stage(new_stage, actor_id) instead.
    ValueError from invalid transitions is caught and returned as 422.
    """
    data, err = parse_body(UpdateApplicationStageSchema)
    if err:
        return err

    try:
        from app.repositories import ApplicationRepository
        from app.models.enums import ApplicationStage
        from flask import g

        repo        = ApplicationRepository()
        application = repo.get_by_id(application_id)

        if not application:
            return error(
                f"Application '{application_id}' not found.",
                code="APPLICATION_NOT_FOUND",
                status=404,
            )

        if application.is_terminal:
            return error(
                f"Application is already in a terminal stage ('{application.stage}'). "
                "No further transitions are allowed.",
                code="TERMINAL_STAGE",
                status=422,
            )

        new_stage = data["stage"]

        # Validate the stage value before calling advance_stage
        try:
            ApplicationStage(new_stage)
        except ValueError:
            return error(
                f"Invalid stage '{new_stage}'.",
                code="INVALID_STAGE",
                status=400,
            )

        # FIX AP-01: use advance_stage() instead of direct attribute assignment.
        # advance_stage() validates the transition graph and appends to stage_history.
        actor_id = data.get("actor_id") or getattr(
            getattr(g, "current_user", None), "id", None
        )
        try:
            application.advance_stage(new_stage, actor_id=actor_id)
        except ValueError as exc:
            return error(str(exc), code="INVALID_TRANSITION", status=422)

        if data.get("recruiter_notes") is not None:
            application.recruiter_notes = data["recruiter_notes"]
        if data.get("rejection_reason") is not None:
            application.rejection_reason = data["rejection_reason"]

        repo.save(application)

        logger.info(
            "Application stage advanced",
            extra={"application_id": application_id, "stage": new_stage, "actor": actor_id},
        )
        return success(
            data=serialize_application(application),
            message=f"Application moved to '{new_stage}'.",
        )
    except Exception:
        logger.error("update_application_stage failed", exc_info=True)
        return error("Failed to update application stage.", code="INTERNAL_ERROR", status=500)


@applications_bp.delete("/<application_id>")
def withdraw_application(application_id: str):
    """
    DELETE /api/v1/applications/<application_id>

    Withdraws the application. Sets stage to WITHDRAWN rather than hard-deleting.
    """
    try:
        from app.repositories import ApplicationRepository
        from app.models.enums import ApplicationStage

        repo        = ApplicationRepository()
        application = repo.get_by_id(application_id)

        if not application:
            return error(
                f"Application '{application_id}' not found.",
                code="APPLICATION_NOT_FOUND",
                status=404,
            )

        current_stage = getattr(application.stage, "value", str(application.stage))
        if current_stage in ("hired", "rejected"):
            return error(
                f"Cannot withdraw an application in '{current_stage}' stage.",
                code="CANNOT_WITHDRAW",
                status=422,
            )

        try:
            application.advance_stage(ApplicationStage.WITHDRAWN.value)
        except ValueError:
            # If WITHDRAWN is not in the transitions graph from current stage,
            # fall back to direct assignment (withdraw is always a valid escape)
            application.stage = ApplicationStage.WITHDRAWN.value

        repo.save(application)

        try:
            from app.repositories import JobRepository
            job = JobRepository().get_by_id(application.job_id)
            if job:
                job.applicant_count = max(0, (getattr(job, "applicant_count", 1) or 1) - 1)
                JobRepository().save(job)
        except Exception:
            logger.warning("Failed to decrement applicant_count", exc_info=True)

        logger.info("Application withdrawn", extra={"application_id": application_id})
        return no_content()
    except Exception:
        logger.error("withdraw_application failed", exc_info=True)
        return error("Failed to withdraw application.", code="INTERNAL_ERROR", status=500)


# ─────────────────────────────────────────────────────────────────────────────
# ATS Score trigger
# ─────────────────────────────────────────────────────────────────────────────

@applications_bp.post("/<application_id>/score")
def score_application(application_id: str):
    """
    POST /api/v1/applications/<application_id>/score

    Trigger or refresh the ATS score for this application.
    """
    body    = request.get_json(silent=True) or {}
    use_llm = bool(body.get("use_llm", True))

    try:
        from app.repositories import ApplicationRepository, ResumeRepository, JobRepository

        application = ApplicationRepository().get_by_id(application_id)
        if not application:
            return error(
                f"Application '{application_id}' not found.",
                code="APPLICATION_NOT_FOUND",
                status=404,
            )

        resume = ResumeRepository().get_by_id(application.resume_id)
        job    = JobRepository().get_by_id(application.job_id)

        if not resume:
            return error("Resume for this application not found.", code="RESUME_NOT_FOUND", status=404)
        if not job:
            return error("Job for this application not found.", code="JOB_NOT_FOUND", status=404)

        svcs   = get_services()
        result = svcs.ats_scorer.score_resume_job(
            resume=resume,
            job=job,
            application_id=application_id,
            use_llm=use_llm and svcs.groq.available,
        )

        if result.error:
            return error(
                f"Scoring failed: {result.error}",
                code="SCORING_FAILED",
                status=500,
            )

        return success(
            data={
                "application_id":        application_id,
                "resume_id":             result.resume_id,
                "job_id":                result.job_id,
                "final_score":           result.final_score,
                "score_label":           result.score_label,
                "semantic_score":        result.semantic_score,
                "keyword_score":         result.keyword_score,
                "experience_score":      result.experience_score,
                "section_quality_score": result.section_quality_score,
                "matched_skills":        result.matched_skills,
                "missing_skills":        result.missing_skills,
                "improvement_tips":      result.improvement_tips,
                "summary_text":          result.summary_text,
                "hiring_recommendation": result.hiring_recommendation,
                "ats_score_id":          result.ats_score_id,
            },
            message="ATS score computed and saved.",
        )
    except Exception:
        logger.error("score_application failed", exc_info=True)
        return error("Failed to score application.", code="INTERNAL_ERROR", status=500)
    

# ─────────────────────────────────────────────────────────────────────────────
# AI Summary
# ─────────────────────────────────────────────────────────────────────────────

@applications_bp.get("/<application_id>/ai-summary")
def get_ai_summary(application_id: str):
    """GET /api/v1/applications/<application_id>/ai-summary"""
    try:
        from app.repositories import ApplicationRepository, AtsScoreRepository, ResumeRepository
        from app.core.security import get_current_user

        app_repo = ApplicationRepository()
        application = app_repo.get_by_id(application_id)
        if not application:
            return error("Application not found.", code="APPLICATION_NOT_FOUND", status=404)

        score = AtsScoreRepository().get_by_resume_and_job(
            resume_id=application.resume_id,
            job_id=application.job_id,
        )
        resume = ResumeRepository().get_by_id(application.resume_id)

        svcs = get_services()
        if not svcs.groq.available:
            return error("AI service unavailable.", code="SERVICE_UNAVAILABLE", status=503)

        candidate_name = getattr(
            getattr(application, "candidate", None), "full_name", "Candidate"
        ) or "Candidate"

        from app.repositories import JobRepository
        job = JobRepository().get_by_id(application.job_id)

        result = svcs.groq.generate_candidate_summary(
            candidate_name=candidate_name,
            job_title=getattr(job, "title", "this role"),
            final_score=getattr(score, "final_score", 0.0) if score else 0.0,
            matched_skills=getattr(score, "matched_skills_list", []) if score else [],
            missing_skills=getattr(score, "missing_skills_list", []) if score else [],
            experience_years=getattr(resume, "total_experience_years", 0.0) if resume else 0.0,
            stage=str(application.stage),
        )

        return success(data=result, message="AI summary generated.")
    except Exception:
        logger.error("get_ai_summary failed", exc_info=True)
        return error("Failed to generate summary.", code="INTERNAL_ERROR", status=500)
