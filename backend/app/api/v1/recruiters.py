"""
app/api/v1/recruiters.py  (JWT-secured revision)

Recruiter resource — profile management and analytics.

Auth changes vs original:
  All write routes require a valid recruiter JWT.
  Recruiters can only read/modify their own profile.
  POST /recruiters/ is REMOVED — use POST /auth/register/recruiter instead.

Routes:
  GET    /recruiters/               — list recruiters        [recruiter]
  GET    /recruiters/<id>           — get own profile        [recruiter, owns]
  PATCH  /recruiters/<id>           — update own profile     [recruiter, owns]
  DELETE /recruiters/<id>           — soft-delete account    [recruiter, owns]
  GET    /recruiters/<id>/jobs      — own job postings       [recruiter, owns]
  GET    /recruiters/<id>/analytics — dashboard metrics      [recruiter, owns]
  GET    /recruiters/<id>/pipeline  — pipeline funnel        [recruiter, owns]
"""

import logging

from flask import Blueprint, request

from app.core.responses import created, error, no_content, success, success_list
from app.core.security import get_current_user, require_auth, require_ownership
from app.schemas.recruiter import RecruiterQuerySchema, UpdateRecruiterSchema

from ._helpers import (
    get_services,
    parse_body,
    parse_query,
    serialize_job,
    serialize_recruiter,
)

logger = logging.getLogger(__name__)

recruiters_bp = Blueprint("recruiters", __name__)


# ─────────────────────────────────────────────────────────────────────────────
# List
# ─────────────────────────────────────────────────────────────────────────────

@recruiters_bp.get("/")
@require_auth("recruiter")
def list_recruiters():
    """
    GET /api/v1/recruiters/

    Recruiter-only — visibility into peer recruiters on the platform.
    Query params: page, limit, search, company_name
    """
    params, err = parse_query(RecruiterQuerySchema)
    if err:
        return err

    try:
        from app.repositories import RecruiterRepository
        items, total = RecruiterRepository().list_active(
            page=params["page"],
            limit=params["limit"],
            search=params.get("search"),
            company_name=params.get("company_name"),
        )
        return success_list(
            data=[serialize_recruiter(r) for r in items],
            total=total,
            page=params["page"],
            limit=params["limit"],
            message="Recruiters retrieved.",
        )
    except Exception:
        logger.error("list_recruiters failed", exc_info=True)
        return error("Failed to retrieve recruiters.", code="INTERNAL_ERROR", status=500)


# ─────────────────────────────────────────────────────────────────────────────
# Single resource
# ─────────────────────────────────────────────────────────────────────────────

@recruiters_bp.get("/<recruiter_id>")
@require_auth("recruiter")
@require_ownership("recruiter_id")
def get_recruiter(recruiter_id: str):
    """GET /api/v1/recruiters/<recruiter_id> — own profile only."""
    try:
        from app.repositories import RecruiterRepository
        recruiter = RecruiterRepository().get_by_id(recruiter_id)

        if not recruiter or not getattr(recruiter, "is_active", True):
            return error(
                f"Recruiter '{recruiter_id}' not found.",
                code="RECRUITER_NOT_FOUND",
                status=404,
            )

        return success(data=serialize_recruiter(recruiter), message="Recruiter retrieved.")
    except Exception:
        logger.error("get_recruiter failed", exc_info=True)
        return error("Failed to retrieve recruiter.", code="INTERNAL_ERROR", status=500)


@recruiters_bp.patch("/<recruiter_id>")
@require_auth("recruiter")
@require_ownership("recruiter_id")
def update_recruiter(recruiter_id: str):
    """PATCH /api/v1/recruiters/<recruiter_id> — update own profile."""
    data, err = parse_body(UpdateRecruiterSchema)
    if err:
        return err

    try:
        from app.repositories import RecruiterRepository
        repo      = RecruiterRepository()
        recruiter = repo.get_by_id(recruiter_id)

        if not recruiter or not getattr(recruiter, "is_active", True):
            return error(
                f"Recruiter '{recruiter_id}' not found.",
                code="RECRUITER_NOT_FOUND",
                status=404,
            )

        _UPDATEABLE = (
            "full_name", "company_name", "company_size",
            "industry", "phone", "website_url", "linkedin_url",
        )
        for field in _UPDATEABLE:
            if field in data:
                setattr(recruiter, field, data[field])

        repo.save(recruiter)
        logger.info("Recruiter updated", extra={"recruiter_id": recruiter_id})
        return success(data=serialize_recruiter(recruiter), message="Recruiter updated.")
    except Exception:
        logger.error("update_recruiter failed", exc_info=True)
        return error("Failed to update recruiter.", code="INTERNAL_ERROR", status=500)


@recruiters_bp.delete("/<recruiter_id>")
@require_auth("recruiter")
@require_ownership("recruiter_id")
def delete_recruiter(recruiter_id: str):
    """DELETE /api/v1/recruiters/<recruiter_id> — soft-delete own account."""
    try:
        from app.repositories import RecruiterRepository
        repo      = RecruiterRepository()
        recruiter = repo.get_by_id(recruiter_id)

        if not recruiter or not getattr(recruiter, "is_active", True):
            return error(
                f"Recruiter '{recruiter_id}' not found.",
                code="RECRUITER_NOT_FOUND",
                status=404,
            )

        repo.soft_delete(recruiter)
        logger.info("Recruiter deleted", extra={"recruiter_id": recruiter_id})
        return no_content()
    except Exception:
        logger.error("delete_recruiter failed", exc_info=True)
        return error("Failed to delete recruiter.", code="INTERNAL_ERROR", status=500)


# ─────────────────────────────────────────────────────────────────────────────
# Sub-resources
# ─────────────────────────────────────────────────────────────────────────────

@recruiters_bp.get("/<recruiter_id>/jobs")
@require_auth("recruiter")
@require_ownership("recruiter_id")
def list_recruiter_jobs(recruiter_id: str):
    """GET /api/v1/recruiters/<recruiter_id>/jobs — own job postings."""
    page   = int(request.args.get("page", 1))
    limit  = min(int(request.args.get("limit", 20)), 100)
    status = request.args.get("status")

    try:
        from app.repositories import RecruiterRepository, JobRepository

        if not RecruiterRepository().get_by_id(recruiter_id):
            return error(
                f"Recruiter '{recruiter_id}' not found.",
                code="RECRUITER_NOT_FOUND",
                status=404,
            )

        items, total = JobRepository().list_by_recruiter(
            recruiter_id=recruiter_id, status=status, page=page, limit=limit,
        )
        return success_list(
            data=[serialize_job(j) for j in items],
            total=total, page=page, limit=limit,
            message="Jobs retrieved.",
        )
    except Exception:
        logger.error("list_recruiter_jobs failed", exc_info=True)
        return error("Failed to retrieve jobs.", code="INTERNAL_ERROR", status=500)


@recruiters_bp.get("/<recruiter_id>/analytics")
@require_auth("recruiter")
@require_ownership("recruiter_id")
def get_recruiter_analytics(recruiter_id: str):
    """GET /api/v1/recruiters/<recruiter_id>/analytics — own dashboard."""
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

        return success(
            data=dashboard.__dict__ if hasattr(dashboard, "__dict__") else dashboard,
            message="Analytics dashboard retrieved.",
        )
    except Exception:
        logger.error("get_recruiter_analytics failed", exc_info=True)
        return error("Failed to retrieve analytics.", code="INTERNAL_ERROR", status=500)


@recruiters_bp.get("/<recruiter_id>/pipeline")
@require_auth("recruiter")
@require_ownership("recruiter_id")
def get_recruiter_pipeline(recruiter_id: str):
    """GET /api/v1/recruiters/<recruiter_id>/pipeline — own pipeline funnel."""
    try:
        from app.repositories import RecruiterRepository
        if not RecruiterRepository().get_by_id(recruiter_id):
            return error(
                f"Recruiter '{recruiter_id}' not found.",
                code="RECRUITER_NOT_FOUND",
                status=404,
            )

        svcs     = get_services()
        pipeline = svcs.recruiter_analytics.get_pipeline(recruiter_id)

        return success(
            data=pipeline.__dict__ if hasattr(pipeline, "__dict__") else pipeline,
            message="Pipeline breakdown retrieved.",
        )
    except Exception:
        logger.error("get_recruiter_pipeline failed", exc_info=True)
        return error("Failed to retrieve pipeline.", code="INTERNAL_ERROR", status=500)