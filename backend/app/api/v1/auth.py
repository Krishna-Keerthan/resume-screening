"""
app/api/v1/auth.py

Authentication resource — JWT-based login, registration and token lifecycle.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta

from flask import Blueprint, g, make_response, request

from app.core.database import db
from app.core.responses import created, error, success
from app.core.security import (
    account_is_usable,
    create_tokens,
    current_account,
    decode_refresh_token,
    get_current_user,
    hash_password,
    require_auth,
    verify_password,
    AuthError,
)
from app.repositories.refresh_token import RefreshTokenRepository
from app.schemas.auth import (
    ChangePasswordSchema,
    LoginSchema,
    RegisterCandidateSchema,
    RegisterRecruiterSchema,
)

from ._helpers import parse_body, serialize_candidate, serialize_recruiter

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)

_COOKIE_NAME     = "refresh_token"
_COOKIE_MAX_AGE  = 7 * 24 * 60 * 60
_COOKIE_SECURE   = False
_COOKIE_HTTPONLY = True
_COOKIE_SAMESITE = "Lax"


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _cookie_secure() -> bool:
    from flask import current_app
    return not current_app.config.get("DEBUG", True)
    # return current_app.config.get("ENV") == "production"


def _set_refresh_cookie(response, refresh_token: str) -> None:
    response.set_cookie(
        _COOKIE_NAME,
        refresh_token,
        max_age=_COOKIE_MAX_AGE,
        httponly=_COOKIE_HTTPONLY,
        secure=_cookie_secure(),
        samesite=_COOKIE_SAMESITE,
        path="/",
    )


def _clear_refresh_cookie(response) -> None:
    response.set_cookie(
        _COOKIE_NAME,
        "",
        max_age=0,
        httponly=_COOKIE_HTTPONLY,
        secure=_cookie_secure(),
        samesite=_COOKIE_SAMESITE,
        path="/",
    )


def _store_refresh_token(jti: str, raw_refresh: str, user_id: str, role: str) -> None:
    """
    Add a hashed refresh token row to the session and flush it. Does not commit.

    The caller owns the transaction: the after_request middleware commits it
    with any 2xx response, and the security-critical routes (refresh, logout,
    logout-all, change-password) commit their revocations before they respond.
    """
    RefreshTokenRepository().create_token(
        jti=jti,
        raw_token=raw_refresh,
        user_id=user_id,
        role=role,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )


def _reject_dead_session(stored):
    """Revoke the presented refresh token and answer 401 for an account that can no longer hold a session."""
    RefreshTokenRepository().revoke(stored)
    db.session.commit()
    resp = make_response(*error(
        "Session is no longer valid. Please log in again.",
        code="TOKEN_INVALID",
        status=401,
    ))
    _clear_refresh_cookie(resp)
    return resp


def _reject_reused_token(user_id: str):
    """A rotated or revoked refresh token was presented again: end every session of its owner."""
    revoked = RefreshTokenRepository().revoke_all_for_user(user_id)
    db.session.commit()
    logger.warning("Refresh token reuse", extra={"user_id": user_id, "revoked_sessions": revoked})
    resp = make_response(*error(
        "Security alert: session invalidated. Please log in again.",
        code="TOKEN_REUSED", status=401))
    _clear_refresh_cookie(resp)
    return resp


def _auth_response(user_dict: dict, role: str, status: int = 200):
    """
    Issue a token pair for user_dict["id"] and build the auth success response.

    Creates the access and refresh tokens, flushes the refresh token's row
    (hash only) into the session, and sets the refresh cookie. It does not
    commit: registration commits the new user row before calling this, and
    the after_request middleware commits the refresh token row with the 2xx
    response.
    """
    from app.core.security import create_tokens

    user_id              = user_dict["id"]
    access, new_refresh_token, jti = create_tokens(user_id, role)

    _store_refresh_token(jti, new_refresh_token, user_id, role)

    body = {
        "success": True,
        "message": "Authentication successful.",
        "data": {
            "access_token": access,
            "token_type":   "Bearer",
            "expires_in":   15 * 60,
            "role":         role,
            "user":         user_dict,
        },
    }

    from flask import jsonify
    response = make_response(jsonify(body), status)
    _set_refresh_cookie(response, new_refresh_token)
    return response


# ─────────────────────────────────────────────────────────────────────────────
# POST /auth/register/candidate
# ─────────────────────────────────────────────────────────────────────────────

@auth_bp.post("/register/candidate")
def register_candidate():
    """
    POST /api/v1/auth/register/candidate

    Body: { full_name, email, password, phone?, location?, headline?,
            open_to_work?, preferred_roles?, preferred_locations?,
            linkedin_url?, github_url?, portfolio_url? }

    Returns: 201 + access token in body + refresh token in HttpOnly cookie.
    """
    data, err = parse_body(RegisterCandidateSchema)
    if err:
        return err

    try:
        from app.repositories import CandidateRepository
        from app.models.candidate import Candidate

        repo  = CandidateRepository()
        email = data["email"].lower().strip()

        if repo.email_exists(email):
            return error(
                f"An account for '{email}' already exists.",
                code="CANDIDATE_EMAIL_CONFLICT",
                status=409,
            )

        candidate                          = Candidate()
        candidate.id                       = str(uuid.uuid4())
        candidate.full_name                = data["full_name"]
        candidate.email                    = email
        candidate.password_hash            = hash_password(data["password"])
        candidate.phone                    = data.get("phone")
        candidate.location                 = data.get("location")
        candidate.headline                 = data.get("headline")
        candidate.open_to_work             = data.get("open_to_work", True)
        candidate.preferred_roles_list     = data.get("preferred_roles", [])
        candidate.preferred_locations_list = data.get("preferred_locations", [])
        candidate.linkedin_url             = data.get("linkedin_url")
        candidate.github_url               = data.get("github_url")
        candidate.portfolio_url            = data.get("portfolio_url")

        repo.save(candidate)  # flush() — row is in session but NOT yet on disk

        

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            return error("Registration failed. Email may already be in use.", 
                        code="INTERNAL_ERROR", status=500)

        logger.info("Candidate registered", extra={"candidate_id": candidate.id})
        return _auth_response(serialize_candidate(candidate), "candidate", status=201)

    except Exception:
        db.session.rollback()
        logger.error("register_candidate failed", exc_info=True)
        return error("Registration failed. Please try again.", code="INTERNAL_ERROR", status=500)


# ─────────────────────────────────────────────────────────────────────────────
# POST /auth/register/recruiter
# ─────────────────────────────────────────────────────────────────────────────

@auth_bp.post("/register/recruiter")
def register_recruiter():
    """
    POST /api/v1/auth/register/recruiter

    Body: { full_name, email, password, company_name, company_size?,
            industry?, phone?, website_url?, linkedin_url? }

    Returns: 201 + access token in body + refresh token in HttpOnly cookie.
    """
    data, err = parse_body(RegisterRecruiterSchema)
    if err:
        return err

    try:
        from app.repositories import RecruiterRepository
        from app.models.recruiter import Recruiter

        repo  = RecruiterRepository()
        email = data["email"].lower().strip()

        if repo.email_exists(email):
            return error(
                f"An account for '{email}' already exists.",
                code="RECRUITER_EMAIL_CONFLICT",
                status=409,
            )

        recruiter               = Recruiter()
        recruiter.id            = str(uuid.uuid4())
        recruiter.full_name     = data["full_name"]
        recruiter.email         = email
        recruiter.password_hash = hash_password(data["password"])
        recruiter.company_name  = data["company_name"]
        recruiter.company_size  = data.get("company_size")
        recruiter.industry      = data.get("industry")
        recruiter.phone         = data.get("phone")
        recruiter.website_url   = data.get("website_url")
        recruiter.linkedin_url  = data.get("linkedin_url")

        repo.save(recruiter)  # flush only

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            return error("Registration failed. Email may already be in use.",
                        code="INTERNAL_ERROR", status=500)

        return _auth_response(serialize_recruiter(recruiter), "recruiter", status=201)

    except Exception:
        db.session.rollback()
        logger.error("register_recruiter failed", exc_info=True)
        return error("Registration failed. Please try again.", code="INTERNAL_ERROR", status=500)


# ─────────────────────────────────────────────────────────────────────────────
# POST /auth/login
# ─────────────────────────────────────────────────────────────────────────────

@auth_bp.post("/login")
def login():
    """
    POST /api/v1/auth/login

    Body: { email, password, role }

    Login only reads from DB — no write before _auth_response, which flushes
    the refresh_token row; the middleware commits it with the 200.
    """
    data, err = parse_body(LoginSchema)
    if err:
        return err

    email    = data["email"].lower().strip()
    password = data["password"]
    role     = data["role"]

    _INVALID = lambda: error(  # noqa: E731
        "Invalid email or password.",
        code="INVALID_CREDENTIALS",
        status=401,
    )

    try:
        if role == "candidate":
            from app.repositories import CandidateRepository
            user = CandidateRepository().get_by_email(email)
            if not account_is_usable(user):
                return _INVALID()
            if not verify_password(password, getattr(user, "password_hash", "") or ""):
                return _INVALID()

            logger.info("Candidate login", extra={"candidate_id": user.id})
            return _auth_response(serialize_candidate(user), "candidate")

        else:  # recruiter
            from app.repositories import RecruiterRepository
            user = RecruiterRepository().get_by_email(email)
            if not account_is_usable(user):
                return _INVALID()
            if not verify_password(password, getattr(user, "password_hash", "") or ""):
                return _INVALID()

            logger.info("Recruiter login", extra={"recruiter_id": user.id})
            return _auth_response(serialize_recruiter(user), "recruiter")

    except Exception:
        db.session.rollback()
        logger.error("login failed", exc_info=True)
        return error("Login failed. Please try again.", code="INTERNAL_ERROR", status=500)


# ─────────────────────────────────────────────────────────────────────────────
# POST /auth/refresh
# ─────────────────────────────────────────────────────────────────────────────

@auth_bp.post("/refresh")
def refresh():
    raw_refresh = request.cookies.get(_COOKIE_NAME)
    if not raw_refresh:
        return error("Refresh token cookie missing. Please log in again.",
                     code="MISSING_TOKEN", status=401)

    try:
        payload = decode_refresh_token(raw_refresh)
    except AuthError as exc:
        resp = make_response(*error(str(exc), code=exc.code, status=401))
        _clear_refresh_cookie(resp)
        return resp

    jti     = payload["jti"]
    user_id = payload["sub"]
    role    = payload["role"]

    tokens = RefreshTokenRepository()
    stored = tokens.get_by_jti(jti)

    if not stored:
        resp = make_response(*error(
            "Refresh token not found. Please log in again.",
            code="TOKEN_INVALID",
            status=401,
        ))
        _clear_refresh_cookie(resp)
        return resp

    if not stored.revoked and not stored.is_valid():
        resp = make_response(*error(
            "Session expired. Please log in again.",
            code="REFRESH_EXPIRED", status=401))
        _clear_refresh_cookie(resp)
        return resp

    try:
        if role == "candidate":
            from app.repositories import CandidateRepository
            user = CandidateRepository().get_by_id(user_id)
            if not account_is_usable(user):
                return _reject_dead_session(stored)
            user_dict = serialize_candidate(user)
        else:
            from app.repositories import RecruiterRepository
            user = RecruiterRepository().get_by_id(user_id)
            if not account_is_usable(user):
                return _reject_dead_session(stored)
            user_dict = serialize_recruiter(user)

        # 1️⃣ Claim the presented token. Only one request can flip revoked
        # from False to True; every other holder of this cookie lost the
        # race or replayed an old token, and is treated as reuse.
        if not tokens.claim(jti):
            return _reject_reused_token(stored.user_id)

        # 2️⃣ Create new refresh token
        access, new_refresh_token , new_jti = create_tokens(user_id, role)
        _store_refresh_token(new_jti, new_refresh_token, user_id, role)

        # 3️⃣ Commit the claim and the new token together
        db.session.commit()

        # 4️⃣ Return response with updated cookie
        body = {
            "success": True,
            "message": "Token refreshed successfully.",
            "data": {
                "access_token": access,
                "token_type": "Bearer",
                "expires_in": 15 * 60,
                "role": role,
                "user": user_dict,
            },
        }
        from flask import jsonify
        response = make_response(jsonify(body), 200)
        _set_refresh_cookie(response, new_refresh_token)
        return response

    except Exception:
        db.session.rollback()
        logger.error("refresh failed", exc_info=True)
        return error("Token refresh failed. Please log in again.",
                     code="INTERNAL_ERROR", status=500)

# ─────────────────────────────────────────────────────────────────────────────
# POST /auth/logout
# ─────────────────────────────────────────────────────────────────────────────

@auth_bp.post("/logout")
@require_auth()
def logout():
    raw_refresh = request.cookies.get(_COOKIE_NAME)

    if raw_refresh:
        tokens = RefreshTokenRepository()
        stored = tokens.get_by_hash(raw_refresh)
        if stored and not stored.revoked:
            tokens.revoke(stored)

            # Commit the revocation before responding: if anything fails
            # after this point the token is already dead.
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                logger.error("logout revocation commit failed", exc_info=True)
                return error("Logout failed.", code="INTERNAL_ERROR", status=500)

    resp = make_response(*success(data=None, message="Logged out successfully."))
    _clear_refresh_cookie(resp)
    logger.info("User logged out", extra={"user_id": g.jwt_user_id, "role": g.jwt_role})
    return resp


# ─────────────────────────────────────────────────────────────────────────────
# POST /auth/logout-all
# ─────────────────────────────────────────────────────────────────────────────

@auth_bp.post("/logout-all")
@require_auth()
def logout_all():
    """
    POST /api/v1/auth/logout-all

    Revokes ALL refresh tokens for the authenticated user.
    """
    user_id, role = get_current_user()

    try:
        count = RefreshTokenRepository().revoke_all_for_user(user_id)

        # Commit now rather than leave it to the middleware: the revocations
        # must persist whatever happens when the response is built.
        db.session.commit()

        logger.info("All tokens revoked", extra={"user_id": user_id, "count": count})
        resp = make_response(
            *success(
                data={"revoked_sessions": count},
                message=f"Signed out from {count} device(s).",
            )
        )
        _clear_refresh_cookie(resp)
        return resp

    except Exception:
        db.session.rollback()
        logger.error("logout_all failed", exc_info=True)
        return error("Logout failed. Please try again.", code="INTERNAL_ERROR", status=500)


# ─────────────────────────────────────────────────────────────────────────────
# GET /auth/me
# ─────────────────────────────────────────────────────────────────────────────

@auth_bp.get("/me")
@require_auth()
def me():
    """
    GET /api/v1/auth/me

    Read-only — no commit needed.
    """
    # require_auth has already loaded the account and rejected dead ones.
    _, role = get_current_user()
    serialize = serialize_candidate if role == "candidate" else serialize_recruiter
    return success(
        data={"role": role, "user": serialize(current_account())},
        message="Profile retrieved.",
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /auth/change-password
# ─────────────────────────────────────────────────────────────────────────────

@auth_bp.post("/change-password")
@require_auth()
def change_password():
    """
    POST /api/v1/auth/change-password

    Body: { current_password, new_password }
    """
    data, err = parse_body(ChangePasswordSchema)
    if err:
        return err

    user_id, role = get_current_user()

    try:
        user = current_account()

        current_hash = getattr(user, "password_hash", "") or ""
        if not verify_password(data["current_password"], current_hash):
            return error(
                "Current password is incorrect.",
                code="INVALID_CREDENTIALS",
                status=401,
            )

        if verify_password(data["new_password"], current_hash):
            return error(
                "New password must differ from the current password.",
                code="VALIDATION_ERROR",
                status=400,
            )

        user.password_hash = hash_password(data["new_password"])
        user.save()

        RefreshTokenRepository().revoke_all_for_user(user_id)

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.error("change_password commit failed", exc_info=True)
            return error("Password change failed.", code="INTERNAL_ERROR", status=500)

        logger.info("Password changed", extra={"user_id": user_id, "role": role})
        resp = make_response(
            *success(data=None, message="Password changed. Please log in again.")
        )
        _clear_refresh_cookie(resp)
        return resp

    except Exception:
        db.session.rollback()
        logger.error("change_password failed", exc_info=True)
        return error("Password change failed. Please try again.", code="INTERNAL_ERROR", status=500)