"""
app/core/security.py

JWT authentication core.

IMPROVEMENTS APPLIED:
  SE-01 — Added assert_owns() ownership assertion helper.
           Ownership checks (does this candidate own this resume?) were
           copy-pasted across 8+ route handlers, each with slightly different
           error messages and response shapes. Centralised here as a single
           helper that raises AuthError with a consistent 403 payload.

  SE-02 — decode_access_token() raised the same AuthError("INVALID_TOKEN")
           for both expired tokens and genuinely invalid ones. Front-ends need
           to distinguish these cases: expired → prompt re-authentication;
           invalid → log out immediately. Added separate error codes:
           EXPIRED_TOKEN and INVALID_TOKEN.

Architecture
───────────
Access token  — short-lived (15 min), sent in Authorization: Bearer <token>
                Stateless; verified purely by signature.

Refresh token — long-lived (7 days), stored as SHA-256 hash in DB.
                Revocable on logout, password change, or suspicious activity.

Token payload
─────────────
{
  "sub":  "<user uuid>",
  "role": "candidate"|"recruiter",
  "type": "access"|"refresh",
  "jti":  "<uuid4>",
  "iat":  <unix timestamp>,
  "exp":  <unix timestamp>
}

Public API
──────────
  create_tokens(user_id, role)            → (access_token, refresh_token, jti)
  decode_access_token(token)              → payload dict  / raises AuthError
  require_auth(*roles)                    → Flask decorator
  get_current_user()                      → (user_id, role) from g
  assert_owns(resource, user_id, msg?)   → raises AuthError(403) if mismatch
  hash_password(plain)                    → hashed string
  verify_password(plain, hashed)          → bool
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta
from functools import wraps
from typing import Any, Callable, Tuple

import jwt
from flask import current_app, g, request

from app.core.responses import error as err_response

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Internal constants
# ─────────────────────────────────────────────────────────────────────────────

_ALGORITHM   = "HS256"
_ACCESS_TTL  = timedelta(minutes=15)
_REFRESH_TTL = timedelta(days=7)


# ─────────────────────────────────────────────────────────────────────────────
# Custom exception
# ─────────────────────────────────────────────────────────────────────────────

class AuthError(Exception):
    """
    Raised when a token cannot be trusted.

    SE-02: code is now set to EXPIRED_TOKEN or INVALID_TOKEN so callers
    can distinguish between the two cases.
    """

    def __init__(
        self,
        message: str,
        code: str = "INVALID_TOKEN",
        status: int = 401,
    ) -> None:
        super().__init__(message)
        self.code   = code
        self.status = status


# ─────────────────────────────────────────────────────────────────────────────
# Token creation
# ─────────────────────────────────────────────────────────────────────────────

def create_tokens(
    user_id: str,
    role: str,
) -> Tuple[str, str, str]:
    """
    Create a linked access + refresh token pair.

    Both tokens share the same JTI so they can be rotated atomically.

    Returns:
        (access_token, refresh_token, jti)
    """
    secret = current_app.config["SECRET_KEY"]
    now    = datetime.now(timezone.utc)
    jti    = str(uuid.uuid4())

    access_ttl  = timedelta(minutes=current_app.config.get("JWT_ACCESS_TTL_MINUTES",  15))
    refresh_ttl = timedelta(days=current_app.config.get("JWT_REFRESH_TTL_DAYS", 7))

    access_payload = {
        "sub":  user_id,
        "role": role,
        "type": "access",
        "jti":  jti,
        "iat":  now,
        "exp":  now + access_ttl,
    }
    refresh_payload = {
        "sub":  user_id,
        "role": role,
        "type": "refresh",
        "jti":  jti,
        "iat":  now,
        "exp":  now + refresh_ttl,
    }

    access_token  = jwt.encode(access_payload,  secret, algorithm=_ALGORITHM)
    refresh_token = jwt.encode(refresh_payload, secret, algorithm=_ALGORITHM)

    return access_token, refresh_token, jti


# ─────────────────────────────────────────────────────────────────────────────
# Token verification
# ─────────────────────────────────────────────────────────────────────────────

def decode_access_token(token: str) -> dict[str, Any]:
    """
    Decode and validate an access token.

    SE-02: Raises AuthError with code="EXPIRED_TOKEN" for expired tokens and
    code="INVALID_TOKEN" for tokens that fail signature/structure validation.
    Front-ends should treat EXPIRED_TOKEN as a cue to refresh, and
    INVALID_TOKEN as a cue to log out immediately.

    Args:
        token: Raw JWT string (without "Bearer " prefix).

    Returns:
        Decoded payload dict.

    Raises:
        AuthError: If the token is expired, tampered, or malformed.
    """
    secret = current_app.config["SECRET_KEY"]
    try:
        payload = jwt.decode(token, secret, algorithms=[_ALGORITHM])
    except jwt.ExpiredSignatureError:
        # SE-02: separate error code for expired tokens
        raise AuthError("Access token has expired.", code="EXPIRED_TOKEN", status=401)
    except jwt.InvalidTokenError as exc:
        raise AuthError(f"Invalid token: {exc}", code="INVALID_TOKEN", status=401)

    if payload.get("type") != "access":
        raise AuthError(
            "Token type mismatch — expected 'access' token.",
            code="INVALID_TOKEN",
            status=401,
        )

    return payload


def decode_refresh_token(token: str) -> dict[str, Any]:
    """
    Decode and validate a refresh token.

    SE-02: Same error-code split as decode_access_token.
    """
    secret = current_app.config["SECRET_KEY"]
    try:
        payload = jwt.decode(token, secret, algorithms=[_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise AuthError("Refresh token has expired.", code="EXPIRED_TOKEN", status=401)
    except jwt.InvalidTokenError as exc:
        raise AuthError(f"Invalid refresh token: {exc}", code="INVALID_TOKEN", status=401)

    if payload.get("type") != "refresh":
        raise AuthError(
            "Token type mismatch — expected 'refresh' token.",
            code="INVALID_TOKEN",
            status=401,
        )

    return payload


# ─────────────────────────────────────────────────────────────────────────────
# Flask request helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_current_user() -> Tuple[str, str] | Tuple[None, None]:
    """
    Return (user_id, role) from the current request context.

    Returns (None, None) when no authenticated user is present.
    Requires middleware to have called verify_jwt_in_request() first.
    """
    user = getattr(g, "current_user", None)
    if user is None:
        return None, None
    return str(user.id), getattr(user, "role", None) or _role_from_model(user)


def _role_from_model(user) -> str:
    """Infer role string from the model class name."""
    class_name = user.__class__.__name__.lower()
    if "recruiter" in class_name:
        return "recruiter"
    return "candidate"


def require_auth(*roles: str) -> Callable:
    """
    Flask route decorator that enforces authentication and optional role check.

    Usage:
        @bp.get("/protected")
        @require_auth("recruiter")
        def protected_route():
            user_id, role = get_current_user()
            ...

    Args:
        *roles: Allowed roles. If empty, any authenticated user is accepted.
    """
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                return err_response(
                    "Missing or malformed Authorization header.",
                    code="MISSING_TOKEN",
                    status=401,
                )

            raw_token = auth_header.removeprefix("Bearer ").strip()
            try:
                payload = decode_access_token(raw_token)
            except AuthError as exc:
                return err_response(str(exc), code=exc.code, status=exc.status)

            user_id = payload.get("sub")
            role    = payload.get("role")

            if roles and role not in roles:
                return err_response(
                    f"Access denied. Required role(s): {', '.join(roles)}.",
                    code="FORBIDDEN",
                    status=403,
                )

            # Store on g for downstream use
            g.jwt_user_id = user_id
            g.jwt_role    = role
            g.jwt_jti     = payload.get("jti")

            return fn(*args, **kwargs)
        return wrapper
    return decorator


# ─────────────────────────────────────────────────────────────────────────────
# SE-01: Ownership assertion helper
# ─────────────────────────────────────────────────────────────────────────────

def assert_owns(
    resource: Any,
    user_id: str,
    owner_attr: str = "candidate_id",
    message: str | None = None,
) -> None:
    """
    Assert that the authenticated user owns the given resource.

    SE-01: Ownership checks were copy-pasted across 8+ route handlers.
    Centralised here with a consistent AuthError(403) response.

    Usage:
        from app.core.security import assert_owns, AuthError

        @bp.get("/<resume_id>")
        @require_auth("candidate")
        def get_resume(resume_id: str):
            resume = ResumeRepository().get_by_id(resume_id)
            try:
                assert_owns(resume, g.jwt_user_id, owner_attr="candidate_id")
            except AuthError as exc:
                return error(str(exc), code=exc.code, status=exc.status)
            ...

    Args:
        resource:    ORM model instance to check.
        user_id:     UUID of the authenticated user (from g.jwt_user_id).
        owner_attr:  Attribute on the resource that holds the owner's UUID.
        message:     Custom error message. Defaults to a generic ownership error.

    Raises:
        AuthError(403): If the resource does not belong to user_id, or if
                        the resource is None.
    """
    if resource is None:
        raise AuthError("Resource not found or access denied.", code="FORBIDDEN", status=403)

    owner_id = getattr(resource, owner_attr, None)
    if owner_id is None:
        raise AuthError(
            f"Resource has no '{owner_attr}' attribute — cannot verify ownership.",
            code="FORBIDDEN",
            status=403,
        )

    if str(owner_id) != str(user_id):
        msg = message or (
            f"Access denied — this resource belongs to a different user."
        )
        raise AuthError(msg, code="FORBIDDEN", status=403)


def require_ownership(id_param: str = "candidate_id") -> Callable:
    """
    Decorator that enforces the authenticated user owns the requested resource.

    The user's ID from the JWT must match the URL path parameter named
    `id_param`.  Recruiters bypass this check for recruiter-scoped routes
    by using require_auth("recruiter") directly.

    Usage:
        @bp.get("/<candidate_id>/resumes")
        @require_auth("candidate")
        @require_ownership("candidate_id")
        def list_resumes(candidate_id): ...
    """
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            resource_id = kwargs.get(id_param) or (args[0] if args else None)
            user_id = getattr(g, "jwt_user_id", None)  # ← was g.user_id, WRONG

            if not user_id or not resource_id:
                return err_response(
                    "Ownership check failed — missing identity.",
                    code="FORBIDDEN",
                    status=403,
                )

            if str(user_id) != str(resource_id):
                return err_response(
                    "You do not have permission to access this resource.",
                    code="FORBIDDEN",
                    status=403,
                )

            return fn(*args, **kwargs)
        return wrapper
    return decorator

# ─────────────────────────────────────────────────────────────────────────────
# Password helpers
# ─────────────────────────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    """Hash a plain-text password using Werkzeug's scrypt/pbkdf2 scheme."""
    from werkzeug.security import generate_password_hash
    return generate_password_hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plain-text password against a Werkzeug hash."""
    from werkzeug.security import check_password_hash
    return check_password_hash(hashed, plain)