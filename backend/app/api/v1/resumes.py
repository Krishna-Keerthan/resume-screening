"""
app/api/v1/resumes.py

Resume resource — management, parsing status, AI analysis.

Changes vs previous version:
  - analyze_resume() with force_reparse=True now downloads bytes from
    storage_service.download_bytes(resume.file_path) instead of reading
    from local disk. Works on Render (ephemeral fs) + Cloudinary.
  - set_active_resume() unchanged in logic but imports are cleaned up.
  - generate_summary() and rewrite_suggestions() unchanged.
  - All other routes unchanged.

Routes:
  GET    /resumes/                    — paginated list
  GET    /resumes/<id>                — get single resume
  DELETE /resumes/<id>                — soft-delete resume
  POST   /resumes/<id>/analyze        — run full AI analysis
  GET    /resumes/<id>/score-preview  — preview ATS score (no save)
  PATCH  /resumes/<id>/set-active     — set as active resume
  POST   /resumes/<id>/generate-summary
  POST   /resumes/<id>/rewrite-suggestions
"""

import logging
import json

from flask import Blueprint, current_app, request

from app.core.responses import error, no_content, success, success_list
from app.schemas.resume import AnalyzeResumeSchema, ResumeQuerySchema

from ._helpers import (
    get_services,
    parse_body,
    parse_query,
    serialize_resume,
)

logger = logging.getLogger(__name__)

resumes_bp = Blueprint("resumes", __name__)


# ─────────────────────────────────────────────────────────────────────────────
# List
# ─────────────────────────────────────────────────────────────────────────────

@resumes_bp.get("/")
def list_resumes():
    """
    GET /api/v1/resumes/
    Query params: page, limit, candidate_id, parse_status
    """
    params, err = parse_query(ResumeQuerySchema)
    if err:
        return err

    try:
        from app.repositories import ResumeRepository
        repo = ResumeRepository()

        if params.get("candidate_id"):
            items, total = repo.list_by_candidate(
                candidate_id=params["candidate_id"],
                active_only=False,
                page=params["page"],
                limit=params["limit"],
            )
        else:
            items, total = repo.list_all(
                page=params["page"],
                limit=params["limit"],
                parse_status=params.get("parse_status"),
            )

        return success_list(
            data=[serialize_resume(r) for r in items],
            total=total,
            page=params["page"],
            limit=params["limit"],
            message="Resumes retrieved.",
        )
    except Exception:
        logger.error("list_resumes failed", exc_info=True)
        return error("Failed to retrieve resumes.", code="INTERNAL_ERROR", status=500)


# ─────────────────────────────────────────────────────────────────────────────
# Single resource
# ─────────────────────────────────────────────────────────────────────────────

@resumes_bp.get("/<resume_id>")
def get_resume(resume_id: str):
    """GET /api/v1/resumes/<resume_id>"""
    try:
        from app.repositories import ResumeRepository
        resume = ResumeRepository().get_by_id(resume_id)

        if not resume or getattr(resume, "is_deleted", False):
            return error(
                f"Resume '{resume_id}' not found.",
                code="RESUME_NOT_FOUND",
                status=404,
            )

        return success(data=serialize_resume(resume), message="Resume retrieved.")
    except Exception:
        logger.error("get_resume failed", exc_info=True)
        return error("Failed to retrieve resume.", code="INTERNAL_ERROR", status=500)


# ─────────────────────────────────────────────────────────────────────────────
# Delete
# ─────────────────────────────────────────────────────────────────────────────

@resumes_bp.delete("/<resume_id>")
def delete_resume(resume_id: str):
    """
    DELETE /api/v1/resumes/<resume_id>

    Soft-deletes the Resume record.
    Also attempts to delete the underlying file from storage (best-effort).
    """
    try:
        from app.repositories import ResumeRepository
        repo   = ResumeRepository()
        resume = repo.get_by_id(resume_id)

        if not resume or getattr(resume, "is_deleted", False):
            return error(
                f"Resume '{resume_id}' not found.",
                code="RESUME_NOT_FOUND",
                status=404,
            )

        # Best-effort: delete file from storage backend
        storage_key = getattr(resume, "storage_key", None) or getattr(resume, "file_path", None)
        if storage_key:
            try:
                from app.services.storage_service import StorageService
                storage = StorageService.from_config(current_app.config)
                storage.delete(storage_key)
            except Exception:
                # Non-fatal — DB record soft-delete still proceeds
                logger.warning(
                    "Failed to delete resume file from storage (non-fatal)",
                    extra={"storage_key": storage_key},
                    exc_info=True,
                )

        repo.soft_delete(resume)
        logger.info("Resume deleted", extra={"resume_id": resume_id})
        return no_content()
    except Exception:
        logger.error("delete_resume failed", exc_info=True)
        return error("Failed to delete resume.", code="INTERNAL_ERROR", status=500)


# ─────────────────────────────────────────────────────────────────────────────
# AI Analysis
# ─────────────────────────────────────────────────────────────────────────────

@resumes_bp.post("/<resume_id>/analyze")
def analyze_resume(resume_id: str):
    """
    POST /api/v1/resumes/<resume_id>/analyze

    Runs the full AI analysis pipeline:
      1. Re-parse file if needed (or if force_refresh=True)
         — downloads bytes from storage_service instead of reading local disk
      2. Compute section quality score
      3. Call Groq for summary, strengths, issues, role suggestions
      4. Persist results to Resume record
      5. Return structured analysis

    Body (optional): { force_refresh: false }

    KEY CHANGE: When force_reparse=True, bytes are fetched from
    storage_service.download_bytes(resume.file_path). This works
    identically for local (reads file) and Cloudinary (HTTP GET).
    No os.path / local file assumptions remain.
    """
    data, err = parse_body(AnalyzeResumeSchema)
    if err:
        return err

    force_refresh = data.get("force_refresh", False)

    try:
        from app.repositories import ResumeRepository
        from app.models.enums import ParseStatus

        resume = ResumeRepository().get_by_id(resume_id)

        if not resume or getattr(resume, "is_deleted", False):
            return error(
                f"Resume '{resume_id}' not found.",
                code="RESUME_NOT_FOUND",
                status=404,
            )

        # ── If force_refresh: re-parse from storage bytes ──────────────────────
        # ResumeAnalysisService.analyse() calls parser.parse(resume.file_path)
        # internally when force_reparse=True — that assumes a local path.
        # We intercept here, download bytes ourselves, then call parse_bytes()
        # so the service layer stays unaware of the storage provider.
        if force_refresh:
            svcs = get_services()
            file_url = getattr(resume, "file_path", None)

            if not file_url:
                return error(
                    "Resume has no stored file URL. Cannot re-parse.",
                    code="NO_FILE_URL",
                    status=422,
                )

            try:
                from app.services.storage_service import StorageService, StorageError
                storage    = StorageService.from_config(current_app.config)
                file_bytes = storage.download_bytes(file_url)
            except Exception as exc:
                logger.error("Failed to download resume for re-parse", exc_info=True)
                return error(
                    f"Failed to retrieve resume file for re-parsing: {exc}",
                    code="FILE_DOWNLOAD_FAILED",
                    status=502,
                )

            # Parse bytes directly — no temp file, no disk dependency
            filename = getattr(resume, "filename", "resume.pdf")
            try:
                parse_result = svcs.resume_parser.parse_bytes(file_bytes, filename)
            except Exception:
                logger.error("parse_bytes failed during force_refresh", exc_info=True)
                return error(
                    "Re-parsing failed unexpectedly.",
                    code="PARSE_FAILED",
                    status=500,
                )

            if not parse_result.success:
                return error(
                    f"Re-parsing failed: {parse_result.parse_error}",
                    code="PARSE_FAILED",
                    status=422,
                )

            # Apply parse result directly onto the resume ORM object
            from app.repositories import ResumeRepository as RR
            repo = RR()
            resume.parse_status           = ParseStatus.SUCCESS
            resume.parse_error_msg        = None
            resume.raw_text               = parse_result.raw_text
            resume.skills_list            = parse_result.skills
            resume.education_list         = parse_result.education
            resume.experience_list        = parse_result.experience
            resume.certifications_list    = parse_result.certifications
            resume.projects_list          = parse_result.projects
            resume.summary_text           = parse_result.summary_text
            resume.total_experience_years = parse_result.total_experience_years
            resume.skill_count            = len(parse_result.skills)
            try:
                resume.oov_skills_list_parsed = parse_result.oov_skills
            except AttributeError:
                pass
            try:
                resume.contact_info = json.dumps(parse_result.contact)
            except AttributeError:
                pass
            repo.save(resume)

            # Now run analysis without re-parse (data is fresh on the ORM object)
            result = svcs.resume_analysis.analyse(resume=resume, force_reparse=False)
        else:
            # Normal path — service handles parse status check internally
            svcs   = get_services()
            result = svcs.resume_analysis.analyse(
                resume=resume,
                force_reparse=False,
            )

        return success(
            data={
                "resume_id":       result.resume_id,
                "summary":         result.summary,
                "strengths":       result.strengths,
                "issues":          result.issues,
                "role_suggestions":result.role_suggestions,
                "improvement_tips":result.improvement_tips,
                "section_quality": result.section_quality,
                "llm_enhanced":    result.llm_enhanced,
                "parse_error":     result.parse_error,
                "resume":          serialize_resume(resume),
            },
            message=(
                "Resume analysis complete."
                if result.llm_enhanced
                else "Resume analysis complete (rule-based — Groq unavailable)."
            ),
        )
    except Exception:
        logger.error("analyze_resume failed", exc_info=True)
        return error("Failed to analyse resume.", code="INTERNAL_ERROR", status=500)


# ─────────────────────────────────────────────────────────────────────────────
# Score Preview (no persistence)
# ─────────────────────────────────────────────────────────────────────────────

@resumes_bp.get("/<resume_id>/score-preview")
def score_preview(resume_id: str):
    """
    GET /api/v1/resumes/<resume_id>/score-preview?job_id=<id>
    Computes ATS score without saving. Fast — no Groq call.
    """
    job_id = request.args.get("job_id")
    if not job_id:
        return error("job_id query parameter is required.", code="MISSING_PARAM", status=400)

    try:
        from app.repositories import ResumeRepository, JobRepository

        resume = ResumeRepository().get_by_id(resume_id)
        if not resume or getattr(resume, "is_deleted", False):
            return error("Resume not found.", code="RESUME_NOT_FOUND", status=404)

        job = JobRepository().get_by_id(job_id)
        if not job or getattr(job, "is_deleted", False):
            return error("Job not found.", code="JOB_NOT_FOUND", status=404)

        svcs = get_services()

        resume_skills     = getattr(resume, "skills_list", []) or []
        resume_experience = getattr(resume, "experience_list", []) or []
        resume_education  = getattr(resume, "education_list", []) or []
        resume_years      = getattr(resume, "total_experience_years", 0.0) or 0.0
        resume_text       = getattr(resume, "raw_text", "") or ""
        job_required      = getattr(job, "required_skills_list", []) or []
        job_nice_to_have  = getattr(job, "nice_to_have_skills_list", []) or []
        job_years         = getattr(job, "experience_years", 0.0) or 0.0

        result = svcs.ats_scorer.score_raw(
            resume_text=resume_text,
            resume_skills=resume_skills,
            resume_experience=resume_experience,
            resume_education=resume_education,
            resume_experience_years=resume_years,
            job_title=getattr(job, "title", ""),
            job_description=getattr(job, "description", ""),
            job_required_skills=job_required,
            job_nice_to_have_skills=job_nice_to_have,
            job_experience_years=job_years,
        )

        explanation = svcs.explainability.explain(
            final_score=result["final_score"],
            semantic_score=result["semantic_score"],
            keyword_score=result["keyword_score"],
            experience_score=result["experience_score"],
            section_quality_score=result["section_quality_score"],
            resume_skills=resume_skills,
            job_title=getattr(job, "title", ""),
            job_required_skills=job_required,
            job_nice_to_have_skills=job_nice_to_have,
            candidate_years=resume_years,
            required_years=job_years,
            use_llm=False,
            weights=result["weights_used"],
            semantic_component_scores=result.get("semantic_component_scores", {}),
        )

        score_label = (
            "excellent" if result["final_score"] >= 0.80 else
            "good"      if result["final_score"] >= 0.65 else
            "fair"      if result["final_score"] >= 0.50 else
            "weak"
        )

        return success(
            data={
                "resume_id":             resume_id,
                "job_id":                job_id,
                "preview":               True,
                "final_score":           result["final_score"],
                "semantic_score":        result["semantic_score"],
                "keyword_score":         result["keyword_score"],
                "experience_score":      result["experience_score"],
                "section_quality_score": result["section_quality_score"],
                "semantic_available":    result["semantic_available"],
                "score_label":           score_label,
                "matched_skills":        explanation.matched_skills,
                "missing_skills":        explanation.missing_skills,
                "extra_skills":          explanation.extra_skills,
                "improvement_tips":      explanation.improvement_tips,
                "summary_text":          explanation.summary,
                "hiring_recommendation": explanation.hiring_recommendation,
                "weights_used":          result["weights_used"],
            },
            message="Score preview computed (not saved).",
        )
    except Exception:
        logger.error("score_preview failed", exc_info=True)
        return error("Failed to compute score preview.", code="INTERNAL_ERROR", status=500)


# ─────────────────────────────────────────────────────────────────────────────
# Set Active
# ─────────────────────────────────────────────────────────────────────────────

@resumes_bp.patch("/<resume_id>/set-active")
def set_active_resume(resume_id: str):
    """
    PATCH /api/v1/resumes/<resume_id>/set-active
    Sets this resume as the active one, deactivates all others for this candidate.
    Only successfully parsed resumes can be set active.
    """
    try:
        from app.repositories import ResumeRepository
        from app.core.database import db
        from app.models.resume import Resume
        from app.core.security import get_current_user
        from app.models.enums import ParseStatus

        user_id, _ = get_current_user()
        repo        = ResumeRepository()
        resume      = repo.get_by_id(resume_id)

        if not resume or getattr(resume, "is_deleted", False):
            return error(f"Resume '{resume_id}' not found.", code="RESUME_NOT_FOUND", status=404)

        if str(resume.candidate_id) != str(user_id):
            return error("Access denied.", code="FORBIDDEN", status=403)

        # Normalise parse_status comparison — handle both enum and string values
        parse_status_val = getattr(resume.parse_status, "value", str(resume.parse_status))
        if parse_status_val != ParseStatus.SUCCESS.value:
            return error(
                "Only successfully parsed resumes can be set as active.",
                code="RESUME_NOT_PARSED",
                status=422,
            )

        db.session.query(Resume).filter(
            Resume.candidate_id == user_id,
            Resume.id != resume_id,
            Resume.is_deleted == False,          # noqa: E712
        ).update({Resume.is_active: False}, synchronize_session=False)
        db.session.flush()

        resume.is_active = True
        db.session.add(resume)
        db.session.commit()

        logger.info(
            "Active resume set",
            extra={"resume_id": resume_id, "candidate_id": user_id},
        )
        return success(data=serialize_resume(resume), message="Active resume updated.")

    except Exception:
        logger.error("set_active_resume failed", exc_info=True)
        return error("Failed to update active resume.", code="INTERNAL_ERROR", status=500)


# ─────────────────────────────────────────────────────────────────────────────
# Generate Summary
# ─────────────────────────────────────────────────────────────────────────────

@resumes_bp.post("/<resume_id>/generate-summary")
def generate_summary(resume_id: str):
    """POST /api/v1/resumes/<resume_id>/generate-summary"""
    from app.core.security import get_current_user
    user_id, _ = get_current_user()

    try:
        from app.repositories import ResumeRepository
        resume = ResumeRepository().get_by_id(resume_id)

        if not resume or getattr(resume, "is_deleted", False):
            return error("Resume not found.", code="RESUME_NOT_FOUND", status=404)

        if str(resume.candidate_id) != str(user_id):
            return error("Access denied.", code="FORBIDDEN", status=403)

        svcs = get_services()
        if not svcs.groq.available:
            return error("AI service unavailable.", code="SERVICE_UNAVAILABLE", status=503)

        body = request.get_json(silent=True) or {}
        result = svcs.groq.generate_resume_summary(
            skills=resume.skills_list,
            experience_years=resume.total_experience_years,
            experience=resume.experience_list,
            education=resume.education_list,
            target_role=body.get("target_role", ""),
        )

        if result.get("summary"):
            from app.repositories import ResumeRepository as RR
            from app.core.database import db
            repo = RR()
            resume.resume_summary = result["summary"]
            repo.save(resume)
            db.session.commit()

        return success(
            data={"summary": result.get("summary", ""), "resume": serialize_resume(resume)},
            message="Summary generated successfully.",
        )
    except Exception:
        logger.error("generate_summary failed", exc_info=True)
        return error("Failed to generate summary.", code="INTERNAL_ERROR", status=500)


# ─────────────────────────────────────────────────────────────────────────────
# Rewrite Suggestions
# ─────────────────────────────────────────────────────────────────────────────

@resumes_bp.post("/<resume_id>/rewrite-suggestions")
def rewrite_suggestions(resume_id: str):
    """POST /api/v1/resumes/<resume_id>/rewrite-suggestions  Body: { job_id }"""
    from app.core.security import get_current_user
    user_id, _ = get_current_user()
    body   = request.get_json(silent=True) or {}
    job_id = body.get("job_id")

    if not job_id:
        return error("job_id is required.", code="MISSING_PARAM", status=400)

    try:
        from app.repositories import ResumeRepository, JobRepository
        resume = ResumeRepository().get_by_id(resume_id)
        job    = JobRepository().get_by_id(job_id)

        if not resume or str(resume.candidate_id) != str(user_id):
            return error("Resume not found.", code="RESUME_NOT_FOUND", status=404)
        if not job:
            return error("Job not found.", code="JOB_NOT_FOUND", status=404)

        svcs = get_services()
        if not svcs.groq.available:
            return error("AI service unavailable.", code="SERVICE_UNAVAILABLE", status=503)

        breakdown = svcs.keyword_matcher.get_skill_breakdown(
            resume_skills=resume.skills_list,
            job_required_skills=job.required_skills_list,
            job_nice_to_have_skills=job.nice_to_have_skills_list,
        )
        missing = breakdown.get("missing", [])[:5]

        all_suggestions = []
        for skill in missing[:3]:
            result = svcs.groq.suggest_bullet_rewrites(
                missing_skill=skill,
                existing_experience=resume.experience_list,
                job_title=job.title,
                candidate_skills=resume.skills_list,
            )
            for s in result.get("suggestions", []):
                all_suggestions.append({**s, "for_skill": skill})

        return success(
            data={
                "missing_skills": missing,
                "suggestions":    all_suggestions,
                "job_title":      job.title,
            },
            message=f"Rewrite suggestions generated for {len(missing)} skill gaps.",
        )
    except Exception:
        logger.error("rewrite_suggestions failed", exc_info=True)
        return error("Failed to generate suggestions.", code="INTERNAL_ERROR", status=500)