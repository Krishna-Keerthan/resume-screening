"""
app/core/rate_limit.py

Flask-Limiter wiring: who a caller is for rate-limiting purposes, where the
limit strings come from, and how storage trouble is reported.

Limit strings live in Flask config (RATE_LIMIT_*) and are read on every
request through config_limit(), so a deployment changes them with an
environment variable and a test changes them with app.config.

Callers are told apart by:
  user_or_ip_key  the user id from a valid access token, else the client IP
  ip_key          the client IP only
  ip_email_key    client IP + the lowercased email in the JSON body (login)
  email_key       the lowercased email alone (login backstop)

Key functions never raise: an unusable body or token falls back to the IP.
The client IP is request.remote_addr, which create_app() takes from the
proxy's X-Forwarded-For (ProxyFix, one trusted hop).
"""
from __future__ import annotations

import logging
import math
import time
from typing import Callable

from flask import Flask, current_app, request
from flask_limiter import Limiter

_FALLBACK_MESSAGE = "falling back to in-memory storage"


def client_ip() -> str:
    return request.remote_addr or "unknown"


_USER_ID_ENVIRON_KEY = "ats.rate_limit.user_id"


def _token_user_id() -> str | None:
    """The user id of a valid access token on this request, else None. Cached per request."""
    if _USER_ID_ENVIRON_KEY not in request.environ:
        user_id = None
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            from app.core.security import decode_access_token
            try:
                user_id = decode_access_token(header.removeprefix("Bearer ").strip()).get("sub")
            except Exception:
                user_id = None
        request.environ[_USER_ID_ENVIRON_KEY] = user_id
    return request.environ[_USER_ID_ENVIRON_KEY]


def user_or_ip_key() -> str:
    user_id = _token_user_id()
    return f"user:{user_id}" if user_id else f"ip:{client_ip()}"


def ip_key() -> str:
    return f"ip:{client_ip()}"


def _body_email() -> str | None:
    body = request.get_json(silent=True)
    email = body.get("email") if isinstance(body, dict) else None
    if isinstance(email, str) and email.strip():
        return email.strip().lower()
    return None


def ip_email_key() -> str:
    email = _body_email()
    return f"ip:{client_ip()}|email:{email}" if email else ip_key()


def email_key() -> str:
    email = _body_email()
    return f"email:{email}" if email else ip_key()


def config_limit(name: str) -> Callable[[], str]:
    """A limit string that is looked up in Flask config on each request."""
    return lambda: current_app.config[name]


class _EscalateFallback(logging.Filter):
    """Flask-Limiter reports a dead storage as a warning; make it an error."""

    def filter(self, record: logging.LogRecord) -> bool:
        if _FALLBACK_MESSAGE in record.getMessage():
            record.levelno = logging.ERROR
            record.levelname = "ERROR"
        return True


def retry_after_seconds(limiter: Limiter) -> int | None:
    """Seconds until the limit that was just breached resets, or None if unknown."""
    current = limiter.current_limit
    if current is None or not current.reset_at:
        return None
    return max(1, math.ceil(current.reset_at - time.time()))


def new_limiter() -> Limiter:
    limiter_logger = logging.getLogger("flask-limiter")
    if not any(isinstance(f, _EscalateFallback) for f in limiter_logger.filters):
        limiter_logger.addFilter(_EscalateFallback())
    return Limiter(
        key_func=user_or_ip_key,
        default_limits=[config_limit("RATE_LIMIT_DEFAULT")],
        in_memory_fallback_enabled=True,
    )


def init_rate_limiting(app: Flask, limiter: Limiter) -> None:
    app.config["RATELIMIT_STORAGE_URI"] = app.config["RATE_LIMIT_STORAGE_URL"]
    limiter.init_app(app)
