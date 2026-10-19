"""
app/api/v1/health.py

Health and readiness check endpoints.

Routes:
  GET  /health          — liveness probe (always 200 if app is running)
  GET  /health/ready    — readiness probe (checks DB + services, reports storage)
  GET  /health/services — detailed per-service status
"""

import logging
import time

from flask import Blueprint, current_app

from app.core.responses import error, success

logger = logging.getLogger(__name__)

health_bp = Blueprint("health", __name__)

_START_TIME = time.time()


@health_bp.get("/health")
def liveness():
    """
    GET /api/v1/health

    Liveness probe — returns 200 if the Flask app is running.
    Used by container orchestrators to know the process is alive.
    """
    return success(
        data={
            "status": "ok",
            "uptime_seconds": round(time.time() - _START_TIME, 1),
        },
        message="Service is alive.",
    )


@health_bp.get("/health/ready")
def readiness():
    """
    GET /api/v1/health/ready

    Readiness probe — checks that the app can serve traffic.
    Returns 200 only if:
      - Database connection is healthy
      - Service layer is initialised
    Also reports whether file storage is reachable, as a bare boolean. That does not
    change the status code: an outage at the storage provider stops uploads and
    downloads, not sign-in or browsing, so it must not take the whole API out of rotation.

    Returns 503 if any critical dependency is unavailable.
    """
    checks = {}
    healthy = True

    # ── Database check ────────────────────────────────────────────────────────
    try:
        from app.core.database import db
        db.session.execute(db.text("SELECT 1"))
        checks["database"] = {"status": "ok"}
    except Exception:
        logger.error("Readiness: database check failed", exc_info=True)
        checks["database"] = {"status": "error", "detail": "Database unavailable."}
        healthy = False

    # ── Service layer check ───────────────────────────────────────────────────
    try:
        svcs = current_app.extensions.get("services")
        if svcs is None:
            checks["services"] = {"status": "error", "detail": "ServiceFactory not initialised."}
            healthy = False
        else:
            checks["services"] = {"status": "ok"}
    except Exception:
        logger.error("Readiness: service check failed", exc_info=True)
        checks["services"] = {"status": "error", "detail": "Service layer unavailable."}
        healthy = False

    # ── Storage (informational) ───────────────────────────────────────────────
    checks["storage"] = {"reachable": _storage_reachable()}

    return (
        success(data={"status": "ready" if healthy else "not_ready", "checks": checks})
        if healthy
        else error(
            "Service not ready.",
            code="NOT_READY",
            status=503,
            details={"checks": checks},
        )
    )


def _storage_reachable() -> bool:
    try:
        return current_app.extensions["storage_probe"]()
    except Exception:
        logger.error("Readiness: storage check failed", exc_info=True)
        return False


@health_bp.get("/health/services")
def service_status():
    """
    GET /api/v1/health/services

    Returns availability booleans only, so the endpoint does not reveal which
    components or versions run behind it:
      - database:        the database answers a query
      - semantic_search: the embedding model is loaded
      - ai_assistance:   the LLM client is configured and live
    """
    svcs = current_app.extensions.get("services")

    embedding_ok = False
    groq_ok      = False

    if svcs:
        embedding_svc = getattr(svcs, "embedding", None)
        groq_svc      = getattr(svcs, "groq", None)
        embedding_ok  = bool(embedding_svc and getattr(embedding_svc, "available", False))
        groq_ok       = bool(groq_svc and getattr(groq_svc, "available", False))

    db_ok = False
    try:
        from app.core.database import db
        db.session.execute(db.text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    return success(
        data={
            "services": {
                "database":        db_ok,
                "semantic_search": embedding_ok,
                "ai_assistance":   groq_ok,
            },
            "all_optional_services_available": embedding_ok and groq_ok,
        },
        message="Service status retrieved.",
    )
