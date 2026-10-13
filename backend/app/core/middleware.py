"""
app/core/middleware.py

Flask middleware hooks registered in create_app().

Responsibilities:
  1. Request ID — correlation ID on every request.
  2. Request logging — METHOD, path, IP at start.
  3. Response logging — status code + elapsed time.
  4. Auth context — record the Bearer token's identity in g.jwt_user_id / g.jwt_role.
  5. Auto-commit — commit the session on 200/201/204 responses, roll back
     on everything else (see _after_request).
  6. Error rollback — rollback on any non-2xx or unhandled exception.
  7. Response headers — inject X-Request-ID.
"""

import logging
import time
import uuid

from flask import Flask, g, request

from app.core.logging import set_request_id

logger = logging.getLogger(__name__)

# Status codes whose commit failure turns the response into a 500.
# 204 also commits, in its own branch of _after_request.
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
        g.pop("_account", None)
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

            except Exception:
                # Silently ignore auth errors here — routes protected by
                # @require_auth will return 401. Public routes are unaffected.
                pass

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
        Runs after every request handler that returned a response.

        Transaction handling, so routes only need to flush:
          - 200 / 201: commit. If the commit fails, roll back and turn the
            response into a 500.
          - 204: commit. If the commit fails, roll back and log, but the
            response stays 204.
          - Any other status (202, other 2xx, 3xx, 4xx, 5xx): roll back.
        An exception that escapes the handler skips this hook; the teardown
        hook rolls back instead.
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