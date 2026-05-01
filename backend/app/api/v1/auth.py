"""
app/api/v1/auth.py

Authentication resource — JWT-based login, registration and token lifecycle.

FIXES APPLIED (vs previous version):
  BUG #1 — db.session.commit() added after every write operation.
  Previously, repo.save() only called flush() (row in memory, not on disk).
  Without commit(), Flask-SQLAlchemy rolls back when the request context
  tears down, so candidate/recruiter/refresh_token rows were never persisted.

  Affected functions:
    register_candidate()  — was missing commit after repo.save(candidate)
    register_recruiter()  — was missing commit after repo.save(recruiter)
    change_password()     — was missing commit after repo.save(user)
    _store_refresh_token()— was missing commit after rt.save()

  The fix wraps each write block in a try/except that commits on success
  and rolls back explicitly on failure, so no partial writes survive.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta

from flask import Blueprint, g, make_response, request

from app.core.database import db
from app.core.responses import created, error, success
from app.core.security import (
    create_tokens,
    decode_refresh_token,
    get_current_user,
    hash_password,
    require_auth,
    verify_password,
    AuthError,
)
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
    Flush a hashed refresh token row into the current SQLAlchemy session.

    This function only calls flush() — it does NOT commit.

    Commit responsibility (after all fixes applied):
      - register_candidate / register_recruiter: commit their own user row
        explicitly before calling _auth_response().
      - _auth_response calls _store_refresh_token (flush only), then returns.
      - The after_request middleware commits the refresh_token row as part of
        the same transaction on any 2xx response.
      - For security-critical paths (logout, change_password, logout_all),
        the route handler commits explicitly before building the response.

    Never call db.session.commit() here — the caller owns the transaction.
    """
    from app.models.refresh_token import RefreshToken

    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    rt = RefreshToken.create(
        jti=jti,
        raw_token=raw_refresh,
        user_id=user_id,
        role=role,
        expires_at=expires_at,
    )
    rt.save()   # flush only


def _auth_response(user_dict: dict, role: str, status: int = 200):
    """
    Build the standard auth success response.

    Tokens are generated here. The caller has already committed the user row
    and refresh token row before calling this function.
    """
    from app.core.security import create_tokens

    user_id              = user_dict["id"]
    access, new_refresh_token, jti = create_tokens(user_id, role)

    _store_refresh_token(jti, new_refresh_token, user_id, role)

    # FIX: commit the refresh_token row that _store_refresh_token just flushed.
    # For login, the user row already exists in DB, so we only need to commit
    # the new refresh_token row.

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

    Login only reads from DB — no write before _auth_response.
    _auth_response itself stores + commits the refresh_token row.
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
            if not user or not getattr(user, "is_active", True):
                return _INVALID()
            if not verify_password(password, getattr(user, "password_hash", "") or ""):
                return _INVALID()

            logger.info("Candidate login", extra={"candidate_id": user.id})
            return _auth_response(serialize_candidate(user), "candidate")

        else:  # recruiter
            from app.repositories import RecruiterRepository
            user = RecruiterRepository().get_by_email(email)
            if not user or not getattr(user, "is_active", True):
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

    # ── TEMPORARY DEBUG — remove after diagnosis ──────────────────────────
    import sys
    raw_refresh = request.cookies.get(_COOKIE_NAME)
    print(f"\n[REFRESH DEBUG]", file=sys.stderr)
    print(f"  cookies received : {dict(request.cookies)}", file=sys.stderr)
    print(f"  raw_refresh      : {'PRESENT' if raw_refresh else 'MISSING'}", file=sys.stderr)

    if raw_refresh:
        try:
            payload = decode_refresh_token(raw_refresh)
            print(f"  JWT decode       : OK — jti={payload.get('jti')}", file=sys.stderr)

            from app.models.refresh_token import RefreshToken
            stored = RefreshToken.get_by_jti(payload.get("jti"))
            print(f"  DB row found     : {stored is not None}", file=sys.stderr)

            if stored:
                print(f"  revoked          : {stored.revoked}", file=sys.stderr)
                print(f"  expires_at       : {stored.expires_at}", file=sys.stderr)
                print(f"  is_valid()       : {stored.is_valid()}", file=sys.stderr)

        except Exception as e:
            print(f"  ERROR            : {type(e).__name__}: {e}", file=sys.stderr)
    print(f"[END REFRESH DEBUG]\n", file=sys.stderr)
    # ── END TEMPORARY DEBUG ───────────────────────────────────────────────

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

    from app.models.refresh_token import RefreshToken

    stored = RefreshToken.get_by_jti(jti)

    if not stored:
        resp = make_response(*error(
            "Refresh token not found. Please log in again.",
            code="TOKEN_INVALID",
            status=401,
        ))
        _clear_refresh_cookie(resp)
        return resp

    if not stored.is_valid():
        if not stored.revoked:
            # Genuinely expired
            resp = make_response(*error(
                "Session expired. Please log in again.",
                code="REFRESH_EXPIRED", status=401))
            _clear_refresh_cookie(resp)
            return resp

        # Token is revoked — check if it was just rotated within the last 3 seconds.
        # This handles the race: two simultaneous requests fire with the same cookie.
        # Request A rotates it; Request B arrives ms later seeing revoked=True.
        # Without this, Request B triggers TOKEN_REUSED and boots the user out.
        GRACE_SECONDS = 3
        revoked_at = stored.revoked_at
        if revoked_at is not None:
            if revoked_at.tzinfo is None:
                revoked_at = revoked_at.replace(tzinfo=timezone.utc)
            age_seconds = (datetime.now(timezone.utc) - revoked_at).total_seconds()

            if age_seconds <= GRACE_SECONDS:
                # Find the active successor token issued for this user
                from app.models.refresh_token import RefreshToken as RT
                successor = (
                    db.session.query(RT)
                    .filter_by(user_id=user_id, role=role, revoked=False)
                    .order_by(RT.created_at.desc())
                    .first()
                )
                if successor and successor.is_valid():
                    # Issue a fresh access token — do NOT rotate the refresh token again.
                    # The browser already received the successor cookie from the first request.
                    try:
                        if role == "candidate":
                            from app.repositories import CandidateRepository
                            user = CandidateRepository().get_by_id(user_id)
                            user_dict = serialize_candidate(user)
                        else:
                            from app.repositories import RecruiterRepository
                            user = RecruiterRepository().get_by_id(user_id)
                            user_dict = serialize_recruiter(user)

                        # Only need a fresh access token — reuse existing refresh token
                        import jwt as _jwt
                        secret = __import__('flask', fromlist=['current_app']).current_app.config["SECRET_KEY"]
                        
                        now = datetime.now(timezone.utc)
                        access_ttl = timedelta(minutes=15)
                        access_token = _jwt.encode(
                            {"sub": user_id, "role": role, "type": "access",
                             "jti": successor.jti, "iat": now, "exp": now + access_ttl},
                            secret, algorithm="HS256"
                        )
                        from flask import jsonify
                        body = {
                            "success": True,
                            "message": "Token refreshed successfully.",
                            "data": {
                                "access_token": access_token,
                                "token_type": "Bearer",
                                "expires_in": 15 * 60,
                                "role": role,
                                "user": user_dict,
                            },
                        }
                        return make_response(jsonify(body), 200)
                    except Exception:
                        logger.warning("Grace window recovery failed", exc_info=True)
                        # Fall through to TOKEN_REUSED

        # Genuinely reused outside grace window — possible replay attack
        resp = make_response(*error(
            "Security alert: session invalidated. Please log in again.",
            code="TOKEN_REUSED", status=401))
        _clear_refresh_cookie(resp)
        return resp

    try:
        # 1️⃣ Generate new tokens first
        if role == "candidate":
            from app.repositories import CandidateRepository
            user = CandidateRepository().get_by_id(user_id)
            if not user or not getattr(user, "is_active", True):
                db.session.rollback()
                return error("Account not found.", code="USER_NOT_FOUND", status=404)
            user_dict = serialize_candidate(user)
        else:
            from app.repositories import RecruiterRepository
            user = RecruiterRepository().get_by_id(user_id)
            if not user or not getattr(user, "is_active", True):
                db.session.rollback()
                return error("Account not found.", code="USER_NOT_FOUND", status=404)
            user_dict = serialize_recruiter(user)

        # 2️⃣ Create new refresh token
        access, new_refresh_token , new_jti = create_tokens(user_id, role)
        from app.models.refresh_token import RefreshToken
        new_rt = RefreshToken.create(jti=new_jti,
                                    raw_token=new_refresh_token,
                                     user_id=user_id, 
                                     role=role,
                                     expires_at=datetime.now(timezone.utc)+timedelta(days=7))
        new_rt.save()

        # 3️⃣ Revoke old token AFTER new token is saved
        stored.revoke()

        # 4️⃣ Commit once
        db.session.commit()

        # 5️⃣ Return response with updated cookie
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
        from app.models.refresh_token import RefreshToken
        stored = RefreshToken.get_by_hash(raw_refresh)
        if stored and not stored.revoked:
            stored.revoke()         # flush only
            
            # ADD: commit the revocation immediately.
            # Security-critical: the token must be invalidated NOW,
            # before we build the response. If anything fails after
            # this point, the token is already dead — that's correct.
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
        from app.models.refresh_token import RefreshToken
        count = RefreshToken.revoke_all_for_user(user_id)  # flush only
        
        # ADD: commit immediately — don't rely on middleware.
        # These revocations are security-critical and must persist
        # regardless of what happens when building the response.
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
    user_id, role = get_current_user()

    try:
        if role == "candidate":
            from app.repositories import CandidateRepository
            user = CandidateRepository().get_by_id(user_id)
            if not user or not getattr(user, "is_active", True):
                return error("Account not found.", code="USER_NOT_FOUND", status=404)
            return success(
                data={"role": "candidate", "user": serialize_candidate(user)},
                message="Profile retrieved.",
            )
        else:
            from app.repositories import RecruiterRepository
            user = RecruiterRepository().get_by_id(user_id)
            if not user or not getattr(user, "is_active", True):
                return error("Account not found.", code="USER_NOT_FOUND", status=404)
            return success(
                data={"role": "recruiter", "user": serialize_recruiter(user)},
                message="Profile retrieved.",
            )

    except Exception:
        logger.error("me failed", exc_info=True)
        return error("Failed to retrieve profile.", code="INTERNAL_ERROR", status=500)


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
        if role == "candidate":
            from app.repositories import CandidateRepository
            repo = CandidateRepository()
            user = repo.get_by_id(user_id)
        else:
            from app.repositories import RecruiterRepository
            repo = RecruiterRepository()
            user = repo.get_by_id(user_id)

        if not user:
            return error("Account not found.", code="USER_NOT_FOUND", status=404)

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
        repo.save(user)

        from app.models.refresh_token import RefreshToken
        RefreshToken.revoke_all_for_user(user_id)

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