"""
app/__init__.py  —  Flask Application Factory

JWT Auth changes (Phase 7):
  - _validate_config() now checks SECRET_KEY strength and logs JWT TTL settings.
  - _init_database() imports refresh_token model so create_all() sees it.
  - Everything else is identical to the Phase 6 factory.

The ONLY function that should be called to create the Flask application.
All wiring happens here in a defined order:
  1. Load config
  2. Configure logging
  3. Initialise extensions (CORS)
  4. Initialise database
  5. Register middleware hooks
  6. Register global error handlers
  7. Initialise service layer (ServiceFactory)
  8. Register blueprints
  9. Validate critical config at startup

This factory pattern ensures:
  - No circular imports (models import db, not the app)
  - Testable (create_app("testing") gets a fresh isolated instance)
  - Deployable (create_app("production") uses env-injected secrets)

Usage:
    # run.py
    from app import create_app
    app = create_app()

    # Tests
    from app import create_app
    app = create_app("testing")
    client = app.test_client()
"""

import logging
import os
from typing import Any

from flask import Flask, jsonify

from app.core.logging import configure_logging
from config import get_config

logger = logging.getLogger(__name__)


def create_app(env: str | None = None) -> Flask:
    """
    Application factory — creates and fully configures a Flask instance.

    Args:
        env: Environment name — 'development' | 'production' | 'testing'.
             Falls back to APP_ENV environment variable, then 'development'.

    Returns:
        Fully configured Flask application.

    Raises:
        EnvironmentError: In production if DATABASE_URL is not set.
        ValueError:       If an unknown environment name is provided.
    """
    # ── 1. Resolve config ─────────────────────────────────────────────────────
    config_class = get_config(env)
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config.from_object(config_class)

    # ── 2. Configure logging (must be first — everything after logs) ──────────
    configure_logging(
        level=app.config.get("LOG_LEVEL", "INFO"),
        fmt=app.config.get("LOG_FORMAT", "json"),
    )

    logger.info(
        "Starting application",
        extra={
            "env":   env or os.getenv("APP_ENV", "development"),
            "debug": app.config.get("DEBUG", False),
        },
    )

    # ── 3. Extensions ─────────────────────────────────────────────────────────
    _init_extensions(app)

    # ── 4. Database ───────────────────────────────────────────────────────────
    _init_database(app)

    # ── 5. Middleware ─────────────────────────────────────────────────────────
    _register_middleware(app)

    # ── 6. Error handlers ─────────────────────────────────────────────────────
    _register_error_handlers(app)

    # ── 7. Service layer ──────────────────────────────────────────────────────
    _init_services(app)

    # ── 8. Blueprints ─────────────────────────────────────────────────────────
    _register_blueprints(app)

    # ── 9. Startup validation ─────────────────────────────────────────────────
    _validate_config(app)

    logger.info("Application ready.", extra={"env": env or os.getenv("APP_ENV", "development")})
    return app


# ─────────────────────────────────────────────────────────────────────────────
# Private setup helpers
# ─────────────────────────────────────────────────────────────────────────────

def _init_extensions(app: Flask) -> None:
    """Initialise Flask extensions."""
    from app.core.extensions import cors

    origins = app.config["ALLOWED_ORIGINS"]

    # Guard: wildcard origin is incompatible with supports_credentials=True.
    # If someone sets ALLOWED_ORIGINS=* in production, fail loudly at boot.
    if "*" in origins:
        raise RuntimeError(
            "ALLOWED_ORIGINS cannot be '*' when supports_credentials=True. "
            "Set it to the exact frontend origin, e.g. https://yourapp.com"
        )

    cors.init_app(
        app,
        resources={r"/api/*": {"origins": origins}},
        supports_credentials=True, 
        allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
        expose_headers=["Content-Type", "X-Request-ID"],
        methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        )
    logger.debug("CORS initialised", extra={"origins": app.config["ALLOWED_ORIGINS"]})


def _init_database(app: Flask) -> None:
    """Initialise SQLAlchemy and create tables (dev/test only — use Alembic in prod)."""
    from app.core.database import init_db
    init_db(app)


def _register_middleware(app: Flask) -> None:
    """Register before/after request hooks."""
    from app.core.middleware import register_middleware
    register_middleware(app)


def _init_services(app: Flask) -> None:
    """
    Build and cache the service layer via ServiceFactory.

    Services are stored in app.extensions["services"] — a lightweight
    registry that persists across requests without circular imports.
    Routes access services via:
        svcs = current_app.extensions["services"]
    """
    try:
        from app.services.service_factory import ServiceFactory
        services = ServiceFactory.create_all(app.config)
        app.extensions["services"] = services
        logger.info(
            "Service layer initialised",
            extra={
                "groq_available":      services.groq.available,
                "embedding_available": services.embedding.available,
            },
        )
    except Exception as exc:
        # Non-fatal: app can boot without services (health endpoints still work)
        logger.error(
            "Service layer failed to initialise",
            extra={"error": str(exc)},
            exc_info=True,
        )
        app.extensions["services"] = None


def _register_error_handlers(app: Flask) -> None:
    """
    Register global JSON error handlers.

    Without these, Flask returns HTML error pages.
    Every unhandled exception is caught here and returned as a JSON envelope
    matching the standard { success, error: { error_code, message } } shape.
    """
    from app.core.exceptions import AppError

    @app.errorhandler(AppError)
    def handle_app_error(exc: AppError) -> tuple:
        """Handle all known domain exceptions."""
        logger.warning(
            "Application error",
            extra={
                "error_code":  exc.error_code,
                "status_code": exc.status_code,
                "message":     exc.message,
            },
        )
        return jsonify({"success": False, "error": exc.to_dict()}), exc.status_code

    @app.errorhandler(400)
    def bad_request(e: Any) -> tuple:
        return jsonify({"success": False, "error": {"error_code": "BAD_REQUEST", "message": "Bad request."}}), 400

    @app.errorhandler(401)
    def unauthorized(e: Any) -> tuple:
        # Flask-JWT-Extended attaches error details to the exception description.
        # Preserve them if present, fall back to MISSING_TOKEN only if nothing else.
        description = getattr(e, "description", "") or ""

        # JWT errors come through with specific messages we can map:
        jwt_code_map = {
            "Token has expired":              ("TOKEN_EXPIRED",  "Your session has expired. Please log in again."),
            "Signature verification failed":  ("INVALID_TOKEN",  "Invalid token. Please log in again."),
            "Not enough segments":            ("INVALID_TOKEN",  "Invalid token. Please log in again."),
            "Invalid header string":          ("INVALID_TOKEN",  "Invalid token. Please log in again."),
        }

        for fragment, (code, message) in jwt_code_map.items():
            if fragment.lower() in str(description).lower():
                return jsonify({
                    "success": False,
                    "error": {"error_code": code, "message": message}
                }), 401

        # Default fallback — genuine "no token provided" case
        return jsonify({
            "success": False,
            "error": {"error_code": "MISSING_TOKEN", "message": "Authentication required."}
        }), 401

    @app.errorhandler(403)
    def forbidden(e: Any) -> tuple:
        return jsonify({"success": False, "error": {"error_code": "FORBIDDEN", "message": "You do not have permission to perform this action."}}), 403

    @app.errorhandler(404)
    def not_found(e: Any) -> tuple:
        return jsonify({"success": False, "error": {"error_code": "NOT_FOUND", "message": "Endpoint not found."}}), 404

    @app.errorhandler(405)
    def method_not_allowed(e: Any) -> tuple:
        return jsonify({"success": False, "error": {"error_code": "METHOD_NOT_ALLOWED", "message": "Method not allowed."}}), 405

    @app.errorhandler(413)
    def payload_too_large(e: Any) -> tuple:
        mb = app.config.get("MAX_CONTENT_LENGTH", 10 * 1024 * 1024) // (1024 * 1024)
        return jsonify({"success": False, "error": {
            "error_code": "PAYLOAD_TOO_LARGE",
            "message":    f"File too large. Maximum allowed size is {mb}MB.",
        }}), 413

    @app.errorhandler(422)
    def unprocessable(e: Any) -> tuple:
        return jsonify({"success": False, "error": {"error_code": "UNPROCESSABLE", "message": "Unprocessable entity."}}), 422

    @app.errorhandler(429)
    def rate_limit(e: Any) -> tuple:
        return jsonify({"success": False, "error": {"error_code": "RATE_LIMIT_EXCEEDED", "message": "Too many requests."}}), 429

    @app.errorhandler(500)
    def internal_error(e: Any) -> tuple:
        logger.error("Unhandled 500 error", extra={"error": str(e)}, exc_info=True)
        return jsonify({"success": False, "error": {"error_code": "INTERNAL_ERROR", "message": "Internal server error."}}), 500

    @app.errorhandler(503)
    def service_unavailable(e: Any) -> tuple:
        return jsonify({"success": False, "error": {"error_code": "SERVICE_UNAVAILABLE", "message": "Service temporarily unavailable."}}), 503

    logger.debug("Error handlers registered.")


def _register_blueprints(app: Flask) -> None:
    """Mount all API blueprints."""
    from app.api.v1 import api_v1_bp
    app.register_blueprint(api_v1_bp, url_prefix="/api/v1")
    logger.debug("Blueprints registered.", extra={"prefix": "/api/v1"})


def _validate_config(app: Flask) -> None:
    """
    Validate critical configuration at startup.

    Fail fast — better to crash at boot than fail on the first request.

    JWT Auth additions:
      - Warns if SECRET_KEY is weak or default (it doubles as JWT signing key).
      - Logs JWT token TTL settings for operational visibility.
    """
    issues = []

    # ── SECRET_KEY (also signs JWTs) ──────────────────────────────────────────
    secret = app.config.get("SECRET_KEY", "")
    weak_defaults = {"", "dev-secret-change-in-production", "change-me", "secret"}
    if not app.config.get("DEBUG"):
        if secret in weak_defaults:
            issues.append(
                "SECRET_KEY must be set to a cryptographically random value in production. "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        elif len(secret) < 32:
            issues.append(
                f"SECRET_KEY is only {len(secret)} characters. "
                "Use at least 32 characters for JWT security."
            )

    # ── JWT TTL sanity checks ─────────────────────────────────────────────────
    access_ttl  = app.config.get("JWT_ACCESS_TTL_MINUTES", 15)
    refresh_ttl = app.config.get("JWT_REFRESH_TTL_DAYS", 7)

    if access_ttl < 1:
        issues.append(f"JWT_ACCESS_TTL_MINUTES={access_ttl} is too short (minimum 1).")
    if access_ttl > 60:
        logger.warning(
            "JWT_ACCESS_TTL_MINUTES is unusually long",
            extra={"value": access_ttl, "recommended": "≤ 15"},
        )
    if refresh_ttl > 90:
        logger.warning(
            "JWT_REFRESH_TTL_DAYS is very long",
            extra={"value": refresh_ttl, "recommended": "≤ 30"},
        )

    logger.info(
        "JWT configuration",
        extra={
            "access_ttl_minutes": access_ttl,
            "refresh_ttl_days":   refresh_ttl,
        },
    )

    # ── Groq API key ──────────────────────────────────────────────────────────
    if not app.config.get("GROQ_API_KEY"):
        logger.warning("GROQ_API_KEY is not set. Groq-powered features will be unavailable.")

    # ── Scoring weight sum ────────────────────────────────────────────────────
    weights = (
        app.config.get("WEIGHT_SEMANTIC", 0)
        + app.config.get("WEIGHT_KEYWORD", 0)
        + app.config.get("WEIGHT_EXPERIENCE", 0)
        + app.config.get("WEIGHT_SECTION_QUALITY", 0)
    )
    if not (0.99 <= weights <= 1.01):
        issues.append(
            f"Matching weights sum to {weights:.3f}, not 1.0. "
            "Check WEIGHT_SEMANTIC + WEIGHT_KEYWORD + WEIGHT_EXPERIENCE + WEIGHT_SECTION_QUALITY."
        )

    if issues:
        for issue in issues:
            logger.error("Configuration issue", extra={"issue": issue})
        if not app.config.get("DEBUG"):
            raise RuntimeError(
                f"Production configuration invalid: {'; '.join(issues)}"
            )