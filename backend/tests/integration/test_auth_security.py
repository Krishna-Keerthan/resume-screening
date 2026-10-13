"""
Security behaviour of the auth endpoints: what they must not leak, and which
accounts may hold a session.
"""

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
