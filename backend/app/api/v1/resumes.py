"""
app/api/v1/resumes.py

Resume resource — management, parsing status, AI analysis.

Every route needs a token. A resume belongs to its candidate; a recruiter may
only read (GET /resumes/<id>) one that was submitted to their job.

Routes:
  GET    /resumes/                    — the caller's resumes             [candidate]
  GET    /resumes/<id>                — get single resume                [owner, or the job's recruiter]
  DELETE /resumes/<id>                — soft-delete resume               [owner]
  POST   /resumes/<id>/analyze        — run full AI analysis             [owner]
  GET    /resumes/<id>/score-preview  — preview ATS score (no save)      [owner]
  PATCH  /resumes/<id>/set-active     — set as active resume             [owner]
  POST   /resumes/<id>/generate-summary                                  [owner]
  POST   /resumes/<id>/rewrite-suggestions                               [owner]
"""

import io
import logging
import json

from flask import Blueprint, current_app, g, request, send_file

from app.core.exceptions import ResumeParserBusy
from app.core.responses import error, no_content, success, success_list
from app.core.security import require_auth
from app.schemas.resume import AnalyzeResumeSchema, ResumeQuerySchema
from app.services.ats_scorer import scorer_inputs

from ._helpers import (
    get_active_job,
    get_owned_resume,
    get_services,
    get_viewable_resume,
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
@require_auth("candidate")
def list_resumes():
    """
    GET /api/v1/resumes/
    The caller's own resumes. Query params: page, limit, parse_status
    """
    params, err = parse_query(ResumeQuerySchema)
    if err:
        return err

    try:
        from app.repositories import ResumeRepository
        repo = ResumeRepository()

        items, total = repo.list_by_candidate(
            candidate_id=g.jwt_user_id,
            active_only=False,
            parse_status=params.get("parse_status"),
            page=params["page"],
            limit=params["limit"],
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
@require_auth("candidate", "recruiter")
def get_resume(resume_id: str):
    """GET /api/v1/resumes/<resume_id>"""
    try:
        resume, err = get_viewable_resume(resume_id)
        if err:
            return err

        return success(data=serialize_resume(resume), message="Resume retrieved.")
    except Exception:
        logger.error("get_resume failed", exc_info=True)
        return error("Failed to retrieve resume.", code="INTERNAL_ERROR", status=500)


# ─────────────────────────────────────────────────────────────────────────────
# Delete
# ─────────────────────────────────────────────────────────────────────────────

@resumes_bp.get("/<resume_id>/download")
@require_auth("candidate", "recruiter")
def download_resume(resume_id: str):
    """
    GET /api/v1/resumes/<resume_id>/download

    The resume's candidate, or a recruiter it was submitted to, may download
    the original file.
      cloudinary — JSON { url, expires_in }: a signed URL that expires after
                   DOWNLOAD_URL_TTL_SECONDS (300).
      local      — the file itself, streamed as an attachment.
    """
    from app.services.storage_service import StorageError, StorageService
    from app.utils.file_helpers import content_type_for, safe_download_name

    resume, err = get_viewable_resume(resume_id)
    if err:
        return err

    key = resume.storage_key
    if not key:
        return error("The stored file for this resume was not found.", code="FILE_NOT_FOUND", status=404)

    storage = StorageService.from_config(current_app.config)
    try:
        if storage.provider == "cloudinary":
            ttl = current_app.config.get("DOWNLOAD_URL_TTL_SECONDS", 300)
            return success(
                data={"url": storage.signed_url(key, ttl=ttl), "expires_in": ttl},
                message="Download link created.",
            )
        data = storage.download_bytes(key)
    except StorageError:
        logger.error("download_resume: storage failed", extra={"resume_id": resume_id}, exc_info=True)
        if storage.provider == "local":
            return error("The stored file for this resume was not found.", code="FILE_NOT_FOUND", status=404)
        return error("The file store is unavailable. Please try again.", code="STORAGE_UNAVAILABLE", status=502)

    ext = getattr(resume.file_type, "value", resume.file_type)
    response = send_file(
        io.BytesIO(data),
        mimetype=content_type_for(ext),
        as_attachment=True,
        download_name=safe_download_name(resume.filename, ext),
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, no-store"
    return response


@resumes_bp.delete("/<resume_id>")
@require_auth("candidate")
def delete_resume(resume_id: str):
    """
    DELETE /api/v1/resumes/<resume_id>

    Soft-deletes the Resume record.
    Also attempts to delete the underlying file from storage (best-effort).
    """
    try:
        from app.repositories import ResumeRepository
        repo   = ResumeRepository()
        resume, err = get_owned_resume(resume_id)
        if err:
            return err

        # Best-effort: delete file from storage backend
        storage_key = resume.storage_key
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
@require_auth("candidate")
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
    storage_service.download_bytes(resume.storage_key). This works
    identically for local (reads file) and Cloudinary (signed URL).
    No os.path / local file assumptions remain.
    """
    data, err = parse_body(AnalyzeResumeSchema)
    if err:
        return err

    force_refresh = data.get("force_refresh", False)

    try:
        from app.models.enums import ParseStatus

        resume, err = get_owned_resume(resume_id)
        if err:
            return err

        # ── If force_refresh: re-parse from storage bytes ──────────────────────
        # ResumeAnalysisService.analyse() calls parser.parse(resume.file_path)
        # internally when force_reparse=True — that assumes a local path.
        # We intercept here, download bytes ourselves, then call parse_bytes()
        # so the service layer stays unaware of the storage provider.
        if force_refresh:
            svcs = get_services()
            storage_key = resume.storage_key

            if not storage_key:
                return error(
                    "Resume has no stored file. Cannot re-parse.",
                    code="NO_STORAGE_KEY",
                    status=422,
                )

            try:
                from app.services.storage_service import StorageService, StorageError
                storage    = StorageService.from_config(current_app.config)
                file_bytes = storage.download_bytes(storage_key)
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
            except ResumeParserBusy:
                raise
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
    except ResumeParserBusy:
        raise
    except Exception:
        logger.error("analyze_resume failed", exc_info=True)
        return error("Failed to analyse resume.", code="INTERNAL_ERROR", status=500)


# ─────────────────────────────────────────────────────────────────────────────
# Score Preview (no persistence)
# ─────────────────────────────────────────────────────────────────────────────

@resumes_bp.get("/<resume_id>/score-preview")
@require_auth("candidate")
def score_preview(resume_id: str):
    """
    GET /api/v1/resumes/<resume_id>/score-preview?job_id=<id>
    Computes ATS score without saving. Fast — no Groq call.
    """
    job_id = request.args.get("job_id")
    if not job_id:
        return error("job_id query parameter is required.", code="MISSING_PARAM", status=400)

    try:
        resume, err = get_owned_resume(resume_id)
        if err:
            return err

        job, err = get_active_job(job_id)
        if err:
            return err

        svcs = get_services()

        inputs = scorer_inputs(resume, job)
        result = svcs.ats_scorer.score_raw(**inputs)

        explanation = svcs.explainability.explain(
            final_score=result["final_score"],
            semantic_score=result["semantic_score"],
            keyword_score=result["keyword_score"],
            experience_score=result["experience_score"],
            section_quality_score=result["section_quality_score"],
            resume_skills=inputs["resume_skills"],
            job_title=inputs["job_title"],
            job_required_skills=inputs["job_required_skills"],
            job_nice_to_have_skills=inputs["job_nice_to_have_skills"],
            candidate_years=inputs["resume_experience_years"],
            required_years=inputs["job_experience_years"],
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
@require_auth("candidate")
def set_active_resume(resume_id: str):
    """
    PATCH /api/v1/resumes/<resume_id>/set-active
    Sets this resume as the active one, deactivates all others for this candidate.
    Only successfully parsed resumes can be set active.
    """
    try:
        from app.core.database import db
        from app.core.security import current_account
        from app.models.resume import Resume
        from app.models.enums import ParseStatus

        resume, err = get_owned_resume(resume_id)
        if err:
            return err
        user_id = current_account().id

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
@require_auth("candidate")
def generate_summary(resume_id: str):
    """POST /api/v1/resumes/<resume_id>/generate-summary"""
    try:
        resume, err = get_owned_resume(resume_id)
        if err:
            return err

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
@require_auth("candidate")
def rewrite_suggestions(resume_id: str):
    """POST /api/v1/resumes/<resume_id>/rewrite-suggestions  Body: { job_id }"""
    body   = request.get_json(silent=True) or {}
    job_id = body.get("job_id")

    if not job_id:
        return error("job_id is required.", code="MISSING_PARAM", status=400)

    try:
        resume, err = get_owned_resume(resume_id)
        if err:
            return err
        job, err = get_active_job(job_id)
        if err:
            return err

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