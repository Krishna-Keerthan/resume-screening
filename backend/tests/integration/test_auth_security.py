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
