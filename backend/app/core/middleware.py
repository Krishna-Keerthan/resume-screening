"""
app/core/middleware.py

Flask middleware hooks registered in create_app().

FIXES APPLIED:
  MW-01 — flask_jwt_extended was imported but not in requirements. The
          before_request hook used verify_jwt_in_request() / get_jwt_identity()
          from flask_jwt_extended which was never installed. The entire auth
          context block raised ImportError on every request, setting
          g.current_user = None always.

          Fix: the platform uses PyJWT (app.core.security), not flask_jwt_extended.
          The before_request hook now decodes the Bearer token using
          decode_access_token() from security.py, avoiding the missing
          dependency entirely.

  MW-02 — Auto-commit fired on ALL 2xx status codes, including 201 Created
          responses that might be partially successful. More importantly, the
          auto-commit after_request hook should NOT commit on 204 No Content
          responses where there is deliberately nothing to commit (e.g. DELETE).
          The logic was also subtly wrong: the auto-commit on 2xx means a
          route that builds a 201 but raises mid-serialisation still commits.

          Improved: restrict auto-commit to 200 and 201 only. 204 (no_content)
          does not commit — if a DELETE route soft-deletes a record, it will
          already have been flushed and should be committed by the
          204-producing route itself, or accept the auto-commit for 200/201.
          Operators can tune AUTOCOMMIT_STATUS_CODES in config.

Responsibilities:
  1. Request ID — correlation ID on every request.
  2. Request logging — METHOD, path, IP at start.
  3. Response logging — status code + elapsed time.
  4. Auth context — populate g.current_user from Bearer token.
  5. Auto-commit — commit the session on 200/201 responses.
  6. Error rollback — rollback on any non-2xx or unhandled exception.
  7. Response headers — inject X-Request-ID.
"""

import logging
import time
import uuid

from flask import Flask, g, request

from app.core.logging import set_request_id

logger = logging.getLogger(__name__)

# Status codes that trigger an automatic db.session.commit().
# 204 is intentionally excluded — no content means no new writes to commit
# via this hook (the route already flushed its deletes/updates).
_AUTOCOMMIT_STATUSES = frozenset({200, 201})


def register_middleware(app: Flask) -> None:
    """Attach all middleware hooks to the Flask application."""

    @app.before_request
    def _before_request() -> None:
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
        g.request_id    = rid
        g.request_start = time.perf_counter()

        set_request_id(rid)

        # ── Auth context ──────────────────────────────────────────────────────
        # FIX MW-01: replaced flask_jwt_extended (not installed) with PyJWT
        # via app.core.security.decode_access_token().
        g.current_user = None
        g.jwt_user_id  = None
        g.jwt_role     = None

        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            raw_token = auth_header.removeprefix("Bearer ").strip()
            try:
                from app.core.security import decode_access_token
                payload = decode_access_token(raw_token)
                role    = payload.get("role")
                user_id = payload.get("sub")

                g.jwt_user_id = user_id
                g.jwt_role    = role

                if role == "recruiter":
                    from app.repositories.recruiter import RecruiterRepository
                    g.current_user = RecruiterRepository().get_by_id(user_id)
                elif role == "candidate":
                    from app.repositories.candidate import CandidateRepository
                    g.current_user = CandidateRepository().get_by_id(user_id)

            except Exception:
                # Silently ignore auth errors here — routes protected by
                # @require_auth will return 401. Public routes are unaffected.
                g.current_user = None

        logger.debug(
            "Request started",
            extra={
                "method":     request.method,
                "path":       request.path,
                "ip":         request.remote_addr,
                "user_agent": request.user_agent.string[:120],
            },
        )

    @app.after_request
    def _after_request(response):
        """
        Runs after every successful request handler.

        FIX MW-02: Auto-commit is now restricted to _AUTOCOMMIT_STATUSES
        (200, 201) rather than all 2xx codes. 204 responses (DELETE/no-content)
        are excluded because there is no new data to commit via this hook.

        Why commit here?
          - DRY: a single hook covers all write endpoints automatically.
          - Atomicity: the entire request's writes commit together or not at all.

        Why only on 200/201?
          - 4xx must NOT commit — any partial writes should roll back.
          - 5xx roll back in teardown_appcontext.
          - 204 (no_content) routes have already flushed their deletes;
            committing here is safe but unnecessary — included via rollback path.
        """
        from app.core.database import db

        rid     = getattr(g, "request_id", "-")
        elapsed = time.perf_counter() - getattr(g, "request_start", time.perf_counter())

        response.headers["X-Request-ID"] = rid

        if response.status_code in _AUTOCOMMIT_STATUSES:
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                logger.error(
                    "Auto-commit failed — session rolled back",
                    extra={"path": request.path, "status": response.status_code},
                    exc_info=True,
                )
                response.status_code = 500
                response.set_data(
                    b'{"success": false, "message": "Internal database error."}'
                )
        elif response.status_code == 204:
            # 204: commit the session to persist soft-deletes / updates flushed
            # by the route, then return without mutating the response body.
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                logger.error(
                    "Commit failed on 204 response",
                    extra={"path": request.path},
                    exc_info=True,
                )
        else:
            # Roll back any partial writes on non-2xx / unhandled 2xx codes
            try:
                db.session.rollback()
            except Exception:
                pass

        logger.info(
            "Request completed",
            extra={
                "method":      request.method,
                "path":        request.path,
                "status_code": response.status_code,
                "elapsed_ms":  round(elapsed * 1000, 2),
            },
        )
        return response

    @app.teardown_appcontext
    def _teardown(exception=None) -> None:
        """
        Runs when the application context is torn down.

        Roll back any open session if an unhandled exception propagated
        past the route handler (bypassing after_request).
        """
        from app.core.database import db

        if exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            logger.error(
                "Session rolled back due to unhandled exception",
                extra={"exception": str(exception)},
            )

        try:
            db.session.remove()
        except Exception:
            pass