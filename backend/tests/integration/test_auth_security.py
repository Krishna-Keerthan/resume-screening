"""
Security behaviour of the auth endpoints: what they must not leak, and which
accounts may hold a session.
"""

import pytest

BASE = "/api/v1/auth"
COOKIE = "refresh_token"


def _login(client, user, role, password):
    r = client.post(f"{BASE}/login", json={
        "email": user.email, "password": password, "role": role,
    })
    assert r.status_code == 200, r.get_json()
    return r


def _refresh_cookie(response) -> str:
    for header in response.headers.getlist("Set-Cookie"):
        if header.startswith(f"{COOKIE}="):
            return header.split(";", 1)[0].split("=", 1)[1]
    raise AssertionError("response set no refresh cookie")


def _cookie_header(raw: str) -> dict:
    return {"Cookie": f"{COOKIE}={raw}"}


# ─── Debug output ─────────────────────────────────────────────────────────────

def test_refresh_does_not_write_the_refresh_token_to_the_console(
    client, candidate_a, account_password, capfd
):
    raw = _refresh_cookie(_login(client, candidate_a, "candidate", account_password))
    capfd.readouterr()

    client.post(f"{BASE}/refresh", headers=_cookie_header(raw))

    captured = capfd.readouterr()
    assert raw not in captured.err
    assert raw not in captured.out


# ─── Account status: login ────────────────────────────────────────────────────

_DEAD_STATES = ("deleted", "inactive")


def _kill(user, state):
    if state == "deleted":
        user.soft_delete()
    else:
        user.is_active = False
    from app.core.database import db
    db.session.commit()


@pytest.fixture()
def account(request, candidate_a, recruiter_a):
    """(user, role) for the role named by the test's `role` parameter."""
    return (candidate_a, "candidate") if request.param == "candidate" else (recruiter_a, "recruiter")


@pytest.mark.parametrize("state", _DEAD_STATES)
@pytest.mark.parametrize("account", ["candidate", "recruiter"], indirect=True)
def test_login_rejects_deleted_and_inactive_accounts(client, account, state, account_password):
    user, role = account
    _kill(user, state)

    r = client.post(f"{BASE}/login", json={
        "email": user.email, "password": account_password, "role": role,
    })

    assert r.status_code == 401
    assert r.get_json()["error"]["error_code"] == "INVALID_CREDENTIALS"
    assert COOKIE not in "".join(r.headers.getlist("Set-Cookie"))


# ─── Account status: refresh ──────────────────────────────────────────────────

def _cleared(response) -> bool:
    cookies = [h for h in response.headers.getlist("Set-Cookie") if h.startswith(f"{COOKIE}=")]
    return bool(cookies) and cookies[0].startswith(f'{COOKIE}=;') and "Max-Age=0" in cookies[0]


@pytest.mark.parametrize("state", _DEAD_STATES)
@pytest.mark.parametrize("account", ["candidate", "recruiter"], indirect=True)
def test_refresh_rejects_a_dead_account_and_revokes_its_token(
    client, account, state, account_password
):
    from app.models.refresh_token import RefreshToken

    user, role = account
    raw = _refresh_cookie(_login(client, user, role, account_password))
    _kill(user, state)

    r = client.post(f"{BASE}/refresh", headers=_cookie_header(raw))

    assert r.status_code == 401
    assert "access_token" not in (r.get_json().get("data") or {})
    assert _cleared(r)
    assert RefreshToken.get_by_hash(raw).revoked is True

    # The revoked token is now dead for good, even if the account came back.
    again = client.post(f"{BASE}/refresh", headers=_cookie_header(raw))
    assert again.status_code == 401


def test_refresh_token_is_dead_after_change_password(
    client, candidate_a, account_password
):
    login = _login(client, candidate_a, "candidate", account_password)
    raw = _refresh_cookie(login)
    token = login.get_json()["data"]["access_token"]

    r = client.post(f"{BASE}/change-password",
                    json={"current_password": account_password, "new_password": "NewSecure@123"},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.get_json()

    after = client.post(f"{BASE}/refresh", headers=_cookie_header(raw))
    assert after.status_code == 401


# ─── Account status: access tokens ────────────────────────────────────────────

@pytest.mark.parametrize("state", _DEAD_STATES)
@pytest.mark.parametrize("account", ["candidate", "recruiter"], indirect=True)
def test_access_token_stops_working_when_the_account_dies(
    client, account, state, headers_for
):
    user, role = account
    headers = headers_for(user)
    assert client.get(f"{BASE}/me", headers=headers).status_code == 200

    _kill(user, state)

    for method, url in (
        ("GET", f"{BASE}/me"),
        ("POST", f"{BASE}/logout"),
        ("POST", f"{BASE}/logout-all"),
    ):
        r = client.open(url, method=method, headers=headers)
        assert r.status_code == 401, f"{method} {url} -> {r.status_code}"
        assert r.get_json()["error"]["error_code"] == "INVALID_TOKEN"


def test_dead_candidate_cannot_use_a_role_protected_route(
    client, candidate_a, headers_for
):
    headers = headers_for(candidate_a)
    _kill(candidate_a, "deleted")

    r = client.patch(f"/api/v1/candidates/{candidate_a.id}",
                     json={"headline": "Still here"}, headers=headers)

    assert r.status_code == 401


def test_access_token_for_a_user_that_does_not_exist_is_rejected(client, candidate_a, headers_for):
    headers = headers_for(candidate_a)
    from app.core.database import db
    db.session.delete(candidate_a)
    db.session.commit()

    assert client.get(f"{BASE}/me", headers=headers).status_code == 401


# ─── Account deletion ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("account", ["candidate", "recruiter"], indirect=True)
def test_deleting_an_account_revokes_all_its_refresh_tokens(
    client, account, account_password
):
    from app.models.refresh_token import RefreshToken

    user, role = account
    first = _login(client, user, role, account_password)
    second = _login(client, user, role, account_password)
    raws = [_refresh_cookie(first), _refresh_cookie(second)]
    token = first.get_json()["data"]["access_token"]

    r = client.delete(f"/api/v1/{role}s/{user.id}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 204

    for raw in raws:
        assert RefreshToken.get_by_hash(raw).revoked is True


def test_deleting_a_candidate_twice_is_rejected_the_second_time(
    client, candidate_a, headers_for
):
    headers = headers_for(candidate_a)
    url = f"/api/v1/candidates/{candidate_a.id}"
    assert client.delete(url, headers=headers).status_code == 204
    assert client.delete(url, headers=headers).status_code == 401


def test_recruiter_cannot_read_a_deleted_candidate(
    client, candidate_a, recruiter_a, headers_for, resume_a
):
    url = f"/api/v1/candidates/{candidate_a.id}"
    assert client.get(url, headers=headers_for(recruiter_a)).status_code == 200

    candidate_a.soft_delete()
    from app.core.database import db
    db.session.commit()

    r = client.get(url, headers=headers_for(recruiter_a))
    assert r.status_code == 404
    assert r.get_json()["error"]["error_code"] == "CANDIDATE_NOT_FOUND"
