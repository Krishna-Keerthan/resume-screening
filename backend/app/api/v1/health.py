"""
app/api/v1/health.py

Health and readiness check endpoints.

Routes:
  GET  /health          — liveness probe (always 200 if app is running)
  GET  /health/ready    — readiness probe (checks DB + services)
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

    Returns 503 if any critical dependency is unavailable.
    """
    checks = {}
    healthy = True

    # ── Database check ────────────────────────────────────────────────────────
    try:
        from app.core.database import db
        db.session.execute(db.text("SELECT 1"))
        checks["database"] = {"status": "ok"}
    except Exception as exc:
        checks["database"] = {"status": "error", "detail": str(exc)}
        healthy = False

    # ── Service layer check ───────────────────────────────────────────────────
    try:
        svcs = current_app.extensions.get("services")
        if svcs is None:
            checks["services"] = {"status": "error", "detail": "ServiceFactory not initialised."}
            healthy = False
        else:
            checks["services"] = {"status": "ok"}
    except Exception as exc:
        checks["services"] = {"status": "error", "detail": str(exc)}
        healthy = False

    status_code = 200 if healthy else 503
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


@health_bp.get("/health/services")
def service_status():
    """
    GET /api/v1/health/services

    Returns per-service availability:
      - embedding:  whether sentence-transformers model is loaded
      - groq:       whether Groq API key is configured + client is live
      - database:   connection pool status
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
                "database":   {"available": db_ok,      "description": "PostgreSQL / SQLite connection"},
                "embedding":  {"available": embedding_ok,"description": "Sentence-transformers (MiniLM)"},
                "groq":       {"available": groq_ok,     "description": "Groq LLM API (Llama 3.1)"},
            },
            "all_optional_services_available": embedding_ok and groq_ok,
        },
        message="Service status retrieved.",
    )
