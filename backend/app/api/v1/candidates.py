"""
app/api/v1/candidates.py

Routes (all need a token):
  GET    /candidates/<id>                 — candidate: self; recruiter: only applicants to their jobs
  PATCH  /candidates/<id>                 — self
  DELETE /candidates/<id>                 — self (soft delete)
  GET    /candidates/<id>/resumes         — candidate: all own; recruiter: those attached to applications to their jobs
  POST   /candidates/<id>/resumes         — upload a resume (self)
  GET    /candidates/<id>/skill-gaps      — self
  GET    /candidates/<id>/win-rate-insights — self

Uploads go through StorageService (Cloudinary or local disk); the file bytes
are read once and used for both storage and parsing.
"""

import logging
import os
import uuid

from flask import Blueprint, current_app, request

from app.core.responses import created, error, no_content, success, success_list
from app.core.security import (
    assert_candidate_applied_to_recruiter,
    get_current_user,
    require_auth,
    require_ownership,
)
from app.schemas.candidate import UpdateCandidateSchema
from app.core.database import db
from app.core.exceptions import ResumeUploadFailed
from app.repositories.refresh_token import RefreshTokenRepository
from app.utils.file_helpers import validate_content, validate_upload

from ._helpers import (
    get_services,
    parse_body,
    serialize_candidate,
    serialize_resume,
)

logger = logging.getLogger(__name__)

candidates_bp = Blueprint("candidates", __name__)

_ALLOWED_EXTENSIONS = {"pdf", "docx"}


# ─────────────────────────────────────────────────────────────────────────────
# Single resource
# ─────────────────────────────────────────────────────────────────────────────

@candidates_bp.get("/<candidate_id>")
@require_auth("candidate", "recruiter")
def get_candidate(candidate_id: str):
    user_id, role = get_current_user()

    if role == "candidate" and user_id != candidate_id:
        return error("You can only view your own profile.", code="FORBIDDEN", status=403)
    if role == "recruiter":
        assert_candidate_applied_to_recruiter(candidate_id, user_id)

    try:
        from app.repositories import CandidateRepository, ResumeRepository
        repo = CandidateRepository()
        candidate = repo.get_active_by_id(candidate_id)

        if not candidate:
            return error(
                f"Candidate '{candidate_id}' not found.",
                code="CANDIDATE_NOT_FOUND",
                status=404,
            )

        data = serialize_candidate(candidate)
        if role == "recruiter":
            resumes, _ = ResumeRepository().list_for_recruiter(
                candidate_id, user_id, active_only=True, limit=100
            )
        else:
            resumes, _ = ResumeRepository().list_by_candidate(
                candidate_id, active_only=True, limit=100
            )
        data["resumes"] = [serialize_resume(r) for r in resumes]

        return success(data=data, message="Candidate retrieved.")
    except Exception:
        logger.error("get_candidate failed", exc_info=True)
        return error("Failed to retrieve candidate.", code="INTERNAL_ERROR", status=500)


@candidates_bp.patch("/<candidate_id>")
@require_auth("candidate")
@require_ownership("candidate_id")
def update_candidate(candidate_id: str):
    data, err = parse_body(UpdateCandidateSchema)
    if err:
        return err

    try:
        from app.repositories import CandidateRepository
        repo = CandidateRepository()
        candidate = repo.get_active_by_id(candidate_id)

        if not candidate:
            return error(
                f"Candidate '{candidate_id}' not found.",
                code="CANDIDATE_NOT_FOUND",
                status=404,
            )

        _UPDATEABLE = (
            "full_name", "phone", "location", "headline",
            "linkedin_url", "github_url", "portfolio_url", "open_to_work",
        )
        for field in _UPDATEABLE:
            if field in data:
                setattr(candidate, field, data[field])

        if "preferred_roles" in data:
            candidate.preferred_roles_list = data["preferred_roles"]
        if "preferred_locations" in data:
            candidate.preferred_locations_list = data["preferred_locations"]

        repo.save(candidate)
        logger.info("Candidate updated", extra={"candidate_id": candidate_id})
        return success(data=serialize_candidate(candidate), message="Candidate updated.")
    except Exception:
        logger.error("update_candidate failed", exc_info=True)
        return error("Failed to update candidate.", code="INTERNAL_ERROR", status=500)


@candidates_bp.delete("/<candidate_id>")
@require_auth("candidate")
@require_ownership("candidate_id")
def delete_candidate(candidate_id: str):
    try:
        from app.repositories import CandidateRepository
        repo = CandidateRepository()
        candidate = repo.get_active_by_id(candidate_id)

        if not candidate:
            return error(
                f"Candidate '{candidate_id}' not found.",
                code="CANDIDATE_NOT_FOUND",
                status=404,
            )

        repo.soft_delete(candidate)
        RefreshTokenRepository().revoke_all_for_user(candidate_id)
        logger.info("Candidate deleted", extra={"candidate_id": candidate_id})
        return no_content()
    except Exception:
        logger.error("delete_candidate failed", exc_info=True)
        return error("Failed to delete candidate.", code="INTERNAL_ERROR", status=500)


# ─────────────────────────────────────────────────────────────────────────────
# Resume sub-resource — LIST
# ─────────────────────────────────────────────────────────────────────────────

@candidates_bp.get("/<candidate_id>/resumes")
@require_auth("candidate", "recruiter")
def list_candidate_resumes(candidate_id: str):
    user_id, role = get_current_user()

    if role == "candidate" and user_id != candidate_id:
        return error("You can only view your own resumes.", code="FORBIDDEN", status=403)
    if role == "recruiter":
        assert_candidate_applied_to_recruiter(candidate_id, user_id)

    page  = int(request.args.get("page", 1))
    limit = min(int(request.args.get("limit", 20)), 100)

    try:
        from app.repositories import CandidateRepository, ResumeRepository
        if not CandidateRepository().get_active_by_id(candidate_id):
            return error(
                f"Candidate '{candidate_id}' not found.",
                code="CANDIDATE_NOT_FOUND",
                status=404,
            )

        if role == "recruiter":
            items, total = ResumeRepository().list_for_recruiter(
                candidate_id=candidate_id, recruiter_id=user_id, page=page, limit=limit,
            )
        else:
            items, total = ResumeRepository().list_by_candidate(
                candidate_id=candidate_id,
                active_only=False,
                page=page,
                limit=limit,
            )
        return success_list(
            data=[serialize_resume(r) for r in items],
            total=total, page=page, limit=limit,
            message="Resumes retrieved.",
        )
    except Exception:
        logger.error("list_candidate_resumes failed", exc_info=True)
        return error("Failed to retrieve resumes.", code="INTERNAL_ERROR", status=500)


# ─────────────────────────────────────────────────────────────────────────────
# Resume sub-resource — UPLOAD
# ─────────────────────────────────────────────────────────────────────────────

@candidates_bp.post("/<candidate_id>/resumes")
@require_auth("candidate")
@require_ownership("candidate_id")
def upload_resume(candidate_id: str):
    """
    POST /api/v1/candidates/<candidate_id>/resumes

    Content-Type: multipart/form-data
    Field: file — PDF or DOCX resume file

    Flow:
      1. validate_upload() — extension + MIME + size checks, then
         validate_content() — the bytes match the extension (file_helpers)
      2. Read file into memory (bytes) — single read, used for both storage + parse
      3. StorageService.upload(bytes) — Cloudinary (prod) or local disk (dev)
      4. Create Resume record with storage URL + public_key
      5. ResumeParserService.parse_bytes(bytes) — no disk I/O on Render
      6. Apply parse results → save → deactivate older resumes
      7. Return serialized resume
    """
    # ── 1. Candidate existence check ──────────────────────────────────────────
    try:
        from app.repositories import CandidateRepository
        if not CandidateRepository().get_active_by_id(candidate_id):
            return error(
                f"Candidate '{candidate_id}' not found.",
                code="CANDIDATE_NOT_FOUND",
                status=404,
            )
    except Exception:
        logger.error("upload_resume: candidate lookup failed", exc_info=True)
        return error("Failed to verify candidate.", code="INTERNAL_ERROR", status=500)

    # ── 2. File presence check ────────────────────────────────────────────────
    if "file" not in request.files:
        return error("No file field in request.", code="NO_FILE_UPLOADED", status=400)

    file = request.files["file"]
    if not file or not file.filename:
        return error("Empty file uploaded.", code="EMPTY_FILE", status=400)

    # ── 3. Validate extension + MIME + size ──────────────────────────────────
    try:
        ext = validate_upload(
            file=file,
            allowed_extensions=_ALLOWED_EXTENSIONS,
            max_size_mb=current_app.config.get("MAX_UPLOAD_MB", 10),
        )
    except ResumeUploadFailed as exc:
        return error(str(exc), code="INVALID_FILE", status=415)

    # ── 4. Read file bytes once — reused for storage AND parsing ─────────────
    try:
        file_bytes = file.read()
        if not file_bytes:
            return error("Uploaded file is empty.", code="EMPTY_FILE", status=400)
    except Exception:
        logger.error("Failed to read uploaded file bytes", exc_info=True)
        return error("Failed to read uploaded file.", code="UPLOAD_FAILED", status=500)

    try:
        validate_content(file_bytes, ext)
    except ResumeUploadFailed as exc:
        return error(str(exc), code="INVALID_FILE", status=415)

    original_filename = file.filename  # keep before stream is closed

    # ── 5. Upload to storage (Cloudinary prod / local dev) ────────────────────
    from app.services.storage_service import StorageService, StorageError
    storage = StorageService.from_config(current_app.config)

    try:
        storage_result = storage.upload(file_bytes=file_bytes, ext=ext)
    except StorageError as exc:
        logger.error("Storage upload failed", exc_info=True)
        return error(f"Failed to store resume file: {exc}", code="UPLOAD_FAILED", status=500)

    # ── 6. Create Resume DB record ─────────────────────────────────────────────
    from app.models.resume import Resume
    from app.models.enums import ParseStatus
    from app.repositories import ResumeRepository

    resume_id = str(uuid.uuid4())
    resume    = Resume()
    resume.id           = resume_id
    resume.candidate_id = candidate_id
    resume.filename     = original_filename
    resume.storage_key  = storage_result.key  # source of truth
    resume.file_path    = storage_result.key  # legacy column, kept equal to storage_key
    resume.file_size_kb = storage_result.size_kb
    resume.file_type    = ext
    resume.parse_status = ParseStatus.PENDING
    resume.is_active    = False  # activated below after deactivating others

    repo = ResumeRepository()
    try:
        repo.save(resume)
    except Exception:
        # Cleanup: delete uploaded file if DB record cannot be created
        try:
            storage.delete(storage_result.key)
        except Exception:
            pass
        logger.error("Failed to create Resume record", exc_info=True)
        return error("Failed to register resume.", code="INTERNAL_ERROR", status=500)

    # ── 7. Parse from bytes — no disk I/O on Render ───────────────────────────
    svcs = get_services()
    parse_result = None
    parsed_ok    = False

    try:
        parse_result = svcs.resume_parser.parse_bytes(file_bytes, original_filename)

        if parse_result.success:
            resume.parse_status           = ParseStatus.SUCCESS
            resume.skills_list            = parse_result.skills
            resume.education_list         = parse_result.education
            resume.experience_list        = parse_result.experience
            resume.certifications_list    = parse_result.certifications
            resume.projects_list          = parse_result.projects
            resume.summary_text           = parse_result.summary_text
            resume.raw_text               = parse_result.raw_text
            resume.total_experience_years = parse_result.total_experience_years
            resume.skill_count            = len(parse_result.skills)

            # Persist OOV skills and contact info if model supports them
            try:
                resume.oov_skills_list_parsed = parse_result.oov_skills
            except AttributeError:
                pass
            try:
                resume.contact_info = parse_result.contact
            except AttributeError:
                pass

            parsed_ok = True
        else:
            resume.parse_status    = ParseStatus.FAILED
            resume.parse_error_msg = parse_result.parse_error

        repo.save(resume)

    except Exception:
        logger.error("Resume parse error (non-fatal)", exc_info=True)
        resume.parse_status    = ParseStatus.FAILED
        resume.parse_error_msg = "Unexpected error during parsing."
        try:
            repo.save(resume)
        except Exception:
            pass

    # ── 8. Atomically deactivate previous resumes, activate this one ──────────
    try:
        db.session.query(Resume).filter(
            Resume.candidate_id == candidate_id,
            Resume.id != resume_id,
            Resume.is_deleted == False,          # noqa: E712
        ).update({Resume.is_active: False}, synchronize_session=False)
        db.session.flush()

        resume.is_active = True
        db.session.add(resume)
        db.session.commit()

    except Exception:
        logger.error("Failed to set resume as active", exc_info=True)
        db.session.rollback()
        # Resume is still saved — just not marked active. Non-fatal.

    logger.info(
        "Resume uploaded",
        extra={
            "resume_id":    resume_id,
            "candidate_id": candidate_id,
            "provider":     storage_result.provider,
            "parsed_ok":    parsed_ok,
        },
    )

    return created(
        data=serialize_resume(resume),
        message=(
            "Resume uploaded and parsed successfully."
            if parsed_ok
            else "Resume uploaded. Parsing encountered issues."
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Skill gaps
# ─────────────────────────────────────────────────────────────────────────────

@candidates_bp.get("/<candidate_id>/skill-gaps")
@require_auth("candidate")
@require_ownership("candidate_id")
def get_candidate_skill_gaps(candidate_id: str):
    try:
        from app.repositories import AtsScoreRepository
        from collections import Counter

        all_missing = AtsScoreRepository().get_missing_skills_for_candidate(candidate_id)
        counts = Counter(all_missing)
        ranked = [
            {"skill": skill, "count": count, "pct": round(count / max(len(all_missing), 1) * 100)}
            for skill, count in counts.most_common(15)
        ]
        return success(
            data={"skill_gaps": ranked, "total_applications_scored": len(set(all_missing))},
            message="Skill gap analysis retrieved.",
        )
    except Exception:
        logger.error("get_candidate_skill_gaps failed", exc_info=True)
        return error("Failed to retrieve skill gaps.", code="INTERNAL_ERROR", status=500)


# ─────────────────────────────────────────────────────────────────────────────
# Win-rate insights
# ─────────────────────────────────────────────────────────────────────────────

@candidates_bp.get("/<candidate_id>/win-rate-insights")
@require_auth("candidate")
@require_ownership("candidate_id")
def get_win_rate_insights(candidate_id: str):
    try:
        from app.repositories import ApplicationRepository, ResumeRepository
        from collections import defaultdict

        apps_with_scores = ApplicationRepository().get_applications_with_scores(candidate_id)
        resume = ResumeRepository().get_active_resume(candidate_id)
        candidate_skills = resume.skills_list if resume else []

        winning_stages = {"shortlisted", "interviewing", "offered", "hired"}
        skill_wins  = defaultdict(int)
        skill_total = defaultdict(int)

        for application, score in apps_with_scores:
            stage   = str(getattr(application, "stage", "")).replace("ApplicationStage.", "")
            matched = getattr(score, "matched_skills_list", []) if score else []

            for skill in matched:
                skill_total[skill] += 1
                if stage in winning_stages:
                    skill_wins[skill] += 1

        insights = []
        for skill in candidate_skills:
            total = skill_total.get(skill, 0)
            if total < 2:
                continue
            wins = skill_wins.get(skill, 0)
            insights.append({
                "skill":    skill,
                "win_rate": round(wins / total, 2),
                "wins":     wins,
                "total":    total,
            })

        insights.sort(key=lambda x: -x["win_rate"])

        return success(
            data={
                "top_performing_skills": insights[:8],
                "total_applications":    len(apps_with_scores),
            },
            message="Win rate insights retrieved.",
        )
    except Exception:
        logger.error("get_win_rate_insights failed", exc_info=True)
        return error("Failed to retrieve insights.", code="INTERNAL_ERROR", status=500)