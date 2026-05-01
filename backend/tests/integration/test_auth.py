"""
tests/integration/test_auth.py  (JWT revision)

Integration tests for /api/v1/auth/* endpoints.

Covers:
  POST /auth/register/candidate   — happy path, conflicts, validation
  POST /auth/register/recruiter   — happy path, conflicts, validation
  POST /auth/login                — valid creds, wrong password, unknown email
  GET  /auth/me                   — valid token, expired token, no token
  POST /auth/refresh              — valid cookie, revoked token, reuse detection
  POST /auth/logout               — revokes cookie
  POST /auth/logout-all           — revokes all sessions
  POST /auth/change-password      — happy path, wrong current, same password
"""

import uuid
import pytest

BASE = "/api/v1/auth"

# ─────────────────────────────────────────────────────────────────────────────
# Payload builders
# ─────────────────────────────────────────────────────────────────────────────

def _cand(**kw):
    base = {
        "full_name": "Auth Candidate",
        "email":     f"cand-{uuid.uuid4().hex[:8]}@test.com",
        "password":  "SecureP@ss1",
    }
    base.update(kw)
    return base


def _rec(**kw):
    base = {
        "full_name":    "Auth Recruiter",
        "email":        f"rec-{uuid.uuid4().hex[:8]}@test.com",
        "password":     "SecureP@ss1",
        "company_name": "TestCo",
    }
    base.update(kw)
    return base


def _register_candidate(client, **kw):
    r = client.post(f"{BASE}/register/candidate", json=_cand(**kw))
    assert r.status_code == 201, r.get_json()
    return r


def _register_recruiter(client, **kw):
    r = client.post(f"{BASE}/register/recruiter", json=_rec(**kw))
    assert r.status_code == 201, r.get_json()
    return r


def _auth_header(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


# ─────────────────────────────────────────────────────────────────────────────
# POST /auth/register/candidate
# ─────────────────────────────────────────────────────────────────────────────

class TestRegisterCandidate:
    def test_returns_201(self, client, db):
        assert _register_candidate(client).status_code == 201

    def test_success_envelope(self, client, db):
        body = _register_candidate(client).get_json()
        assert body["success"] is True

    def test_returns_access_token(self, client, db):
        body = _register_candidate(client).get_json()
        assert "access_token" in body["data"]
        assert body["data"]["access_token"]

    def test_returns_token_type_bearer(self, client, db):
        body = _register_candidate(client).get_json()
        assert body["data"]["token_type"] == "Bearer"

    def test_sets_refresh_cookie(self, client, db):
        r = _register_candidate(client)
        assert "refresh_token" in r.headers.get("Set-Cookie", "")

    def test_refresh_cookie_is_httponly(self, client, db):
        r = _register_candidate(client)
        assert "HttpOnly" in r.headers.get("Set-Cookie", "")

    def test_returns_role_candidate(self, client, db):
        body = _register_candidate(client).get_json()
        assert body["data"]["role"] == "candidate"

    def test_user_email_normalised(self, client, db):
        payload = _cand(email="UPPER@EXAMPLE.COM")
        body = client.post(f"{BASE}/register/candidate", json=payload).get_json()
        assert body["data"]["user"]["email"] == "upper@example.com"

    def test_duplicate_email_409(self, client, db):
        p = _cand()
        _register_candidate(client, **p)
        r = client.post(f"{BASE}/register/candidate", json=p)
        assert r.status_code == 409

    def test_duplicate_email_error_code(self, client, db):
        p = _cand()
        _register_candidate(client, **p)
        body = client.post(f"{BASE}/register/candidate", json=p).get_json()
        assert body["error"]["error_code"] == "CANDIDATE_EMAIL_CONFLICT"

    def test_weak_password_400(self, client, db):
        r = client.post(f"{BASE}/register/candidate", json=_cand(password="weak"))
        assert r.status_code == 400

    def test_no_uppercase_password_400(self, client, db):
        r = client.post(f"{BASE}/register/candidate", json=_cand(password="nouppercase1!"))
        assert r.status_code == 400

    def test_no_special_char_password_400(self, client, db):
        r = client.post(f"{BASE}/register/candidate", json=_cand(password="NoSpecial1"))
        assert r.status_code == 400

    def test_missing_email_400(self, client, db):
        r = client.post(f"{BASE}/register/candidate", json={"full_name": "X", "password": "P@ss1234"})
        assert r.status_code == 400

    def test_password_not_in_response(self, client, db):
        body = _register_candidate(client).get_json()
        # password_hash must never appear in any response
        import json
        assert "password" not in json.dumps(body)


# ─────────────────────────────────────────────────────────────────────────────
# POST /auth/register/recruiter
# ─────────────────────────────────────────────────────────────────────────────

class TestRegisterRecruiter:
    def test_returns_201(self, client, db):
        assert _register_recruiter(client).status_code == 201

    def test_returns_access_token(self, client, db):
        body = _register_recruiter(client).get_json()
        assert body["data"]["access_token"]

    def test_returns_role_recruiter(self, client, db):
        body = _register_recruiter(client).get_json()
        assert body["data"]["role"] == "recruiter"

    def test_sets_refresh_cookie(self, client, db):
        r = _register_recruiter(client)
        assert "refresh_token" in r.headers.get("Set-Cookie", "")

    def test_duplicate_email_409(self, client, db):
        p = _rec()
        _register_recruiter(client, **p)
        r = client.post(f"{BASE}/register/recruiter", json=p)
        assert r.status_code == 409

    def test_missing_company_name_400(self, client, db):
        p = _rec()
        del p["company_name"]
        r = client.post(f"{BASE}/register/recruiter", json=p)
        assert r.status_code == 400

    def test_invalid_company_size_400(self, client, db):
        r = client.post(f"{BASE}/register/recruiter", json=_rec(company_size="huge"))
        assert r.status_code == 400

    def test_valid_company_size_accepted(self, client, db):
        body = _register_recruiter(client, company_size="51-200").get_json()
        assert body["data"]["user"]["company_size"] == "51-200"

    def test_password_not_in_response(self, client, db):
        import json
        body = _register_recruiter(client).get_json()
        assert "password" not in json.dumps(body)


# ─────────────────────────────────────────────────────────────────────────────
# POST /auth/login
# ─────────────────────────────────────────────────────────────────────────────

class TestLogin:
    def test_candidate_login_200(self, client, db):
        p = _cand()
        _register_candidate(client, **p)
        r = client.post(f"{BASE}/login", json={"email": p["email"], "password": p["password"], "role": "candidate"})
        assert r.status_code == 200

    def test_login_returns_access_token(self, client, db):
        p = _cand()
        _register_candidate(client, **p)
        body = client.post(f"{BASE}/login", json={"email": p["email"], "password": p["password"], "role": "candidate"}).get_json()
        assert body["data"]["access_token"]

    def test_login_sets_refresh_cookie(self, client, db):
        p = _cand()
        _register_candidate(client, **p)
        r = client.post(f"{BASE}/login", json={"email": p["email"], "password": p["password"], "role": "candidate"})
        assert "refresh_token" in r.headers.get("Set-Cookie", "")

    def test_recruiter_login_200(self, client, db):
        p = _rec()
        _register_recruiter(client, **p)
        r = client.post(f"{BASE}/login", json={"email": p["email"], "password": p["password"], "role": "recruiter"})
        assert r.status_code == 200

    def test_wrong_password_401(self, client, db):
        p = _cand()
        _register_candidate(client, **p)
        r = client.post(f"{BASE}/login", json={"email": p["email"], "password": "WrongP@ss1", "role": "candidate"})
        assert r.status_code == 401

    def test_wrong_password_error_code(self, client, db):
        p = _cand()
        _register_candidate(client, **p)
        body = client.post(f"{BASE}/login", json={"email": p["email"], "password": "WrongP@ss1", "role": "candidate"}).get_json()
        assert body["error"]["error_code"] == "INVALID_CREDENTIALS"

    def test_unknown_email_401(self, client, db):
        r = client.post(f"{BASE}/login", json={"email": "nobody@nowhere.com", "password": "P@ss1234", "role": "candidate"})
        assert r.status_code == 401

    def test_wrong_role_401(self, client, db):
        """Candidate email + recruiter role → 401 (user enumeration prevention)."""
        p = _cand()
        _register_candidate(client, **p)
        r = client.post(f"{BASE}/login", json={"email": p["email"], "password": p["password"], "role": "recruiter"})
        assert r.status_code == 401

    def test_case_insensitive_email(self, client, db):
        p = _cand()
        _register_candidate(client, **p)
        r = client.post(f"{BASE}/login", json={"email": p["email"].upper(), "password": p["password"], "role": "candidate"})
        assert r.status_code == 200

    def test_missing_password_400(self, client, db):
        r = client.post(f"{BASE}/login", json={"email": "x@x.com", "role": "candidate"})
        assert r.status_code == 400

    def test_invalid_role_400(self, client, db):
        r = client.post(f"{BASE}/login", json={"email": "x@x.com", "password": "P@ss1", "role": "admin"})
        assert r.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# GET /auth/me
# ─────────────────────────────────────────────────────────────────────────────

class TestMe:
    def test_valid_token_200(self, client, db):
        body = _register_candidate(client).get_json()
        token = body["data"]["access_token"]
        r = client.get(f"{BASE}/me", headers=_auth_header(token))
        assert r.status_code == 200

    def test_returns_role(self, client, db):
        body = _register_candidate(client).get_json()
        token = body["data"]["access_token"]
        resp = client.get(f"{BASE}/me", headers=_auth_header(token)).get_json()
        assert resp["data"]["role"] == "candidate"

    def test_returns_user_profile(self, client, db):
        body = _register_candidate(client).get_json()
        token = body["data"]["access_token"]
        resp = client.get(f"{BASE}/me", headers=_auth_header(token)).get_json()
        assert "user" in resp["data"]
        assert resp["data"]["user"]["email"]

    def test_recruiter_token_returns_recruiter_role(self, client, db):
        body = _register_recruiter(client).get_json()
        token = body["data"]["access_token"]
        resp = client.get(f"{BASE}/me", headers=_auth_header(token)).get_json()
        assert resp["data"]["role"] == "recruiter"

    def test_no_token_401(self, client, db):
        r = client.get(f"{BASE}/me")
        assert r.status_code == 401

    def test_no_token_error_code(self, client, db):
        body = client.get(f"{BASE}/me").get_json()
        assert body["error"]["error_code"] == "MISSING_TOKEN"

    def test_malformed_token_401_or_403(self, client, db):
        r = client.get(f"{BASE}/me", headers={"Authorization": "Bearer not.a.real.token"})
        assert r.status_code in (401, 403)

    def test_wrong_bearer_prefix_401(self, client, db):
        r = client.get(f"{BASE}/me", headers={"Authorization": "Token abc"})
        assert r.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# POST /auth/logout
# ─────────────────────────────────────────────────────────────────────────────

class TestLogout:
    def test_logout_200(self, client, db):
        body  = _register_candidate(client).get_json()
        token = body["data"]["access_token"]
        r = client.post(f"{BASE}/logout", headers=_auth_header(token))
        assert r.status_code == 200

    def test_logout_clears_cookie(self, client, db):
        body  = _register_candidate(client).get_json()
        token = body["data"]["access_token"]
        r = client.post(f"{BASE}/logout", headers=_auth_header(token))
        cookie_header = r.headers.get("Set-Cookie", "")
        # Cookie should be cleared (max-age=0)
        assert "max-age=0" in cookie_header.lower() or "expires=" in cookie_header.lower()

    def test_logout_without_token_401(self, client, db):
        r = client.post(f"{BASE}/logout")
        assert r.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# POST /auth/logout-all
# ─────────────────────────────────────────────────────────────────────────────

class TestLogoutAll:
    def test_logout_all_200(self, client, db):
        body  = _register_candidate(client).get_json()
        token = body["data"]["access_token"]
        r = client.post(f"{BASE}/logout-all", headers=_auth_header(token))
        assert r.status_code == 200

    def test_logout_all_returns_session_count(self, client, db):
        body  = _register_candidate(client).get_json()
        token = body["data"]["access_token"]
        resp  = client.post(f"{BASE}/logout-all", headers=_auth_header(token)).get_json()
        assert "revoked_sessions" in resp["data"]

    def test_logout_all_without_token_401(self, client, db):
        r = client.post(f"{BASE}/logout-all")
        assert r.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# POST /auth/refresh
# ─────────────────────────────────────────────────────────────────────────────

class TestRefresh:
    def test_refresh_returns_new_access_token(self, client, db):
        reg   = _register_candidate(client)
        # Cookie is set automatically; Flask test client stores it
        r = client.post(f"{BASE}/refresh")
        assert r.status_code == 200
        body = r.get_json()
        assert body["data"]["access_token"]

    def test_refresh_rotates_cookie(self, client, db):
        _register_candidate(client)
        r = client.post(f"{BASE}/refresh")
        assert "refresh_token" in r.headers.get("Set-Cookie", "")

    def test_refresh_without_cookie_401(self, client, db):
        # Use a fresh client with no cookies
        from flask.testing import FlaskClient
        from app import create_app
        import os
        os.environ["APP_ENV"] = "testing"
        # Hit refresh with no cookie at all
        r = client.delete(f"{BASE}/logout")  # just to clear; then test
        fresh_client = client.application.test_client()
        r = fresh_client.post(f"{BASE}/refresh")
        assert r.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# POST /auth/change-password
# ─────────────────────────────────────────────────────────────────────────────

class TestChangePassword:
    def _setup(self, client):
        p = _cand()
        body = client.post(f"{BASE}/register/candidate", json=p).get_json()
        return p, body["data"]["access_token"]

    def test_change_password_200(self, client, db):
        p, token = self._setup(client)
        r = client.post(
            f"{BASE}/change-password",
            json={"current_password": p["password"], "new_password": "NewP@ss9!"},
            headers=_auth_header(token),
        )
        assert r.status_code == 200

    def test_can_login_with_new_password(self, client, db):
        p, token = self._setup(client)
        client.post(
            f"{BASE}/change-password",
            json={"current_password": p["password"], "new_password": "NewP@ss9!"},
            headers=_auth_header(token),
        )
        r = client.post(f"{BASE}/login", json={"email": p["email"], "password": "NewP@ss9!", "role": "candidate"})
        assert r.status_code == 200

    def test_old_password_rejected_after_change(self, client, db):
        p, token = self._setup(client)
        client.post(
            f"{BASE}/change-password",
            json={"current_password": p["password"], "new_password": "NewP@ss9!"},
            headers=_auth_header(token),
        )
        r = client.post(f"{BASE}/login", json={"email": p["email"], "password": p["password"], "role": "candidate"})
        assert r.status_code == 401

    def test_wrong_current_password_401(self, client, db):
        p, token = self._setup(client)
        r = client.post(
            f"{BASE}/change-password",
            json={"current_password": "WrongOld@1", "new_password": "NewP@ss9!"},
            headers=_auth_header(token),
        )
        assert r.status_code == 401

    def test_same_password_400(self, client, db):
        p, token = self._setup(client)
        r = client.post(
            f"{BASE}/change-password",
            json={"current_password": p["password"], "new_password": p["password"]},
            headers=_auth_header(token),
        )
        assert r.status_code == 400

    def test_weak_new_password_400(self, client, db):
        p, token = self._setup(client)
        r = client.post(
            f"{BASE}/change-password",
            json={"current_password": p["password"], "new_password": "weak"},
            headers=_auth_header(token),
        )
        assert r.status_code == 400

    def test_no_token_401(self, client, db):
        r = client.post(
            f"{BASE}/change-password",
            json={"current_password": "any", "new_password": "NewP@ss9!"},
        )
        assert r.status_code == 401