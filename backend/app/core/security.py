"""
app/core/security.py

JWT authentication core.

Architecture
───────────
Access token  — short-lived (15 min), sent in Authorization: Bearer <token>
                Verified by signature; require_auth also loads the account and
                rejects missing, inactive and deleted ones.

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
  assert_owns(resource, user_id, owner_attr=...)  → raises AuthError(403) if mismatch
  assert_can_view_application / assert_can_view_score
  assert_recruiter_can_view_resume / assert_candidate_applied_to_recruiter
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

    code is EXPIRED_TOKEN or INVALID_TOKEN so callers can tell the two apart.
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

    Raises AuthError with code="EXPIRED_TOKEN" for expired tokens and
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

    Same EXPIRED_TOKEN / INVALID_TOKEN split as decode_access_token.
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
    Return (user_id, role) of the account the request's access token names.

    Returns (None, None) when there is no valid token or the account is dead.
    """
    user = current_account()
    if user is None:
        return None, None
    return str(user.id), getattr(user, "role", None) or _role_from_model(user)


def _role_from_model(user) -> str:
    """Infer role string from the model class name."""
    class_name = user.__class__.__name__.lower()
    if "recruiter" in class_name:
        return "recruiter"
    return "candidate"


def current_account():
    """
    The usable account named by the request's access token, or None.

    Loaded at most once per request; the middleware resets the cache and
    records the token's identity in g.jwt_user_id / g.jwt_role.
    """
    if "_account" not in g:
        g._account = _load_account(g.get("jwt_user_id"), g.get("jwt_role"))
        if not account_is_usable(g._account):
            g._account = None
    return g._account


def account_is_usable(user) -> bool:
    """True if the account may log in or hold a session: it exists, is active and is not deleted."""
    return user is not None and bool(user.is_active) and not user.is_deleted


def _load_account(user_id: str | None, role: str | None):
    """Load the candidate or recruiter a token claims to belong to, or None."""
    if not user_id:
        return None
    if role == "candidate":
        from app.repositories.candidate import CandidateRepository
        return CandidateRepository().get_by_id(user_id)
    if role == "recruiter":
        from app.repositories.recruiter import RecruiterRepository
        return RecruiterRepository().get_by_id(user_id)
    return None


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

            g.jwt_user_id = user_id
            g.jwt_role    = role
            g.pop("_account", None)
            if current_account() is None:
                return err_response(
                    "Account is no longer active.",
                    code="INVALID_TOKEN",
                    status=401,
                )

            if roles and role not in roles:
                return err_response(
                    f"Access denied. Required role(s): {', '.join(roles)}.",
                    code="FORBIDDEN",
                    status=403,
                )

            g.jwt_jti = payload.get("jti")

            return fn(*args, **kwargs)
        return wrapper
    return decorator


# ─────────────────────────────────────────────────────────────────────────────
# Ownership assertions
# ─────────────────────────────────────────────────────────────────────────────

def _forbidden(message: str = "Access denied.") -> AuthError:
    return AuthError(message, code="FORBIDDEN", status=403)


def assert_owns(
    resource: Any,
    user_id: str,
    *,
    owner_attr: str,
    message: str | None = None,
) -> None:
    """
    Assert that the authenticated user owns the given resource.

    Args:
        resource:    ORM model instance to check.
        user_id:     id of the authenticated user (g.jwt_user_id).
        owner_attr:  Attribute on the resource that holds the owner's id.
        message:     Custom error message. Defaults to a generic ownership error.

    Raises:
        AuthError(403): If the resource is None, has no such attribute, or
                        does not belong to user_id. The app turns an uncaught
                        AuthError into a JSON error response.
    """
    if resource is None:
        raise _forbidden("Resource not found or access denied.")

    owner_id = getattr(resource, owner_attr, None)
    if owner_id is None:
        raise _forbidden(f"Resource has no '{owner_attr}' — cannot verify ownership.")

    if str(owner_id) != str(user_id):
        raise _forbidden(message or "Access denied — this resource belongs to a different user.")


def assert_can_view_application(application: Any, user_id: str, role: str) -> None:
    """The candidate who applied, or the recruiter who owns the job, may view it."""
    if application is None:
        raise _forbidden("Resource not found or access denied.")
    if role == "candidate" and str(application.candidate_id) == str(user_id):
        return
    if role == "recruiter" and str(application.job.recruiter_id) == str(user_id):
        return
    raise _forbidden("Access denied — you cannot view this application.")


def assert_can_view_score(score: Any, user_id: str, role: str) -> None:
    """The owner of the scored résumé, or the recruiter who owns the scored job, may view it."""
    if score is None:
        raise _forbidden("Resource not found or access denied.")
    if role == "candidate" and str(score.resume.candidate_id) == str(user_id):
        return
    if role == "recruiter" and str(score.job.recruiter_id) == str(user_id):
        return
    raise _forbidden("Access denied — you cannot view this score.")


def assert_recruiter_can_view_resume(resume: Any, recruiter_id: str) -> None:
    """A recruiter may view a résumé only if it is attached to an application to one of their jobs."""
    if resume is None:
        raise _forbidden("Resource not found or access denied.")

    from app.core.database import db
    from app.models.application import Application
    from app.models.job import Job

    linked = (
        db.session.query(Application.id)
        .join(Job, Job.id == Application.job_id)
        .filter(Application.resume_id == resume.id, Job.recruiter_id == recruiter_id)
        .first()
    )
    if linked is None:
        raise _forbidden("Access denied — this resume was not submitted to one of your jobs.")


def assert_candidate_applied_to_recruiter(candidate_id: str, recruiter_id: str) -> None:
    """A recruiter may see a candidate only if that candidate applied to one of the recruiter's jobs."""
    from app.core.database import db
    from app.models.application import Application
    from app.models.job import Job

    linked = (
        db.session.query(Application.id)
        .join(Job, Job.id == Application.job_id)
        .filter(
            Application.candidate_id == candidate_id,
            Job.recruiter_id == recruiter_id,
            Job.is_deleted == False,  # noqa: E712
        )
        .first()
    )
    if linked is None:
        raise _forbidden("Access denied — this candidate has not applied to one of your jobs.")


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