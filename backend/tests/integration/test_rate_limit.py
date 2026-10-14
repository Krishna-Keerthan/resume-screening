"""
Rate limiting: the default per-caller limit, how callers are told apart, the
429 response, the health exemption and the storage fallback.

The test app runs the limiter for real with very high limits; a test lowers a
limit by setting the config value (limits are read on every request).
"""
import logging

import pytest
from flask import Flask

PING = "/api/v1/jobs"          # public GET, cheap
ME = "/api/v1/auth/me"


def _get(client, url, headers=None, ip=None):
    return client.get(url, headers=headers or {}, environ_overrides={"REMOTE_ADDR": ip} if ip else {})


# ─── the default limit ────────────────────────────────────────────────────────

def test_requests_over_the_default_limit_get_429_in_the_error_envelope(client, limit):
    limit("RATE_LIMIT_DEFAULT", "2 per minute")
    assert _get(client, PING).status_code == 200
    assert _get(client, PING).status_code == 200
    r = _get(client, PING)
    assert r.status_code == 429
    assert r.get_json() == {"success": False, "error": {
        "error_code": "RATE_LIMIT_EXCEEDED", "message": "Too many requests."}}
    assert 0 < int(r.headers["Retry-After"]) <= 61      # one-minute window, reset rounded up


def test_only_the_429_carries_retry_after(client, limit):
    limit("RATE_LIMIT_DEFAULT", "1 per minute")
    ok = _get(client, PING)
    assert "Retry-After" not in ok.headers and "X-RateLimit-Limit" not in ok.headers
    assert "Retry-After" in _get(client, PING).headers


def test_anonymous_callers_are_told_apart_by_ip(client, limit):
    limit("RATE_LIMIT_DEFAULT", "1 per minute")
    assert _get(client, PING, ip="10.0.0.1").status_code == 200
    assert _get(client, PING, ip="10.0.0.1").status_code == 429
    assert _get(client, PING, ip="10.0.0.2").status_code == 200


def test_signed_in_users_on_one_ip_have_separate_budgets(
    client, db, limit, candidate_a, candidate_b, headers_for
):
    limit("RATE_LIMIT_DEFAULT", "2 per minute")
    a, b = headers_for(candidate_a), headers_for(candidate_b)
    assert [_get(client, ME, a).status_code for _ in range(3)] == [200, 200, 429]
    assert _get(client, ME, b).status_code == 200


def test_a_user_keeps_one_budget_when_the_ip_changes(client, db, limit, candidate_a, headers_for):
    limit("RATE_LIMIT_DEFAULT", "2 per minute")
    a = headers_for(candidate_a)
    assert _get(client, ME, a, ip="10.0.0.1").status_code == 200
    assert _get(client, ME, a, ip="10.0.0.2").status_code == 200
    assert _get(client, ME, a, ip="10.0.0.3").status_code == 429


def test_a_forged_token_is_counted_against_the_ip_not_the_claimed_user(client, db, limit, candidate_a):
    import jwt
    limit("RATE_LIMIT_DEFAULT", "1 per minute")
    forged = jwt.encode({"sub": str(candidate_a.id), "role": "candidate", "type": "access"},
                        "not-the-secret", algorithm="HS256")
    headers = {"Authorization": f"Bearer {forged}"}
    assert _get(client, ME, headers, ip="10.0.0.1").status_code == 401
    assert _get(client, ME, headers, ip="10.0.0.1").status_code == 429
    assert _get(client, ME, headers, ip="10.0.0.2").status_code == 401


@pytest.mark.parametrize("path", ["/api/v1/health", "/api/v1/health/ready", "/api/v1/health/services"])
def test_health_endpoints_are_never_limited(client, limit, path):
    limit("RATE_LIMIT_DEFAULT", "1 per minute")
    assert [_get(client, path).status_code != 429 for _ in range(4)] == [True] * 4


def test_a_non_health_route_in_the_same_app_is_still_limited(client, limit):
    limit("RATE_LIMIT_DEFAULT", "1 per minute")
    _get(client, "/api/v1/health")
    assert _get(client, PING).status_code == 200
    assert _get(client, PING).status_code == 429


# ─── storage ──────────────────────────────────────────────────────────────────

def test_the_storage_url_setting_reaches_the_limiter_and_an_outage_falls_back_to_memory(caplog):
    from app.core.rate_limit import init_rate_limiting, new_limiter

    app = Flask(__name__)
    app.config.update(RATE_LIMIT_STORAGE_URL="redis://127.0.0.1:1/0", RATE_LIMIT_DEFAULT="1 per minute")
    lim = new_limiter()
    init_rate_limiting(app, lim)

    @app.get("/x")
    def x():
        return "ok"

    client = app.test_client()
    with caplog.at_level(logging.WARNING, logger="flask-limiter"):
        first = client.get("/x")
        second = client.get("/x")

    assert first.status_code == 200          # served from the in-memory fallback, not a 500
    assert second.status_code == 429         # and still limited
    fallback = [r for r in caplog.records if "falling back to in-memory" in r.getMessage()]
    assert fallback and all(r.levelno == logging.ERROR for r in fallback)


def test_a_memory_url_works_without_any_fallback_noise(caplog):
    from app.core.rate_limit import init_rate_limiting, new_limiter

    app = Flask(__name__)
    app.config.update(RATE_LIMIT_STORAGE_URL="memory://", RATE_LIMIT_DEFAULT="1 per minute")
    init_rate_limiting(app, new_limiter())

    @app.get("/x")
    def x():
        return "ok"

    client = app.test_client()
    with caplog.at_level(logging.WARNING, logger="flask-limiter"):
        assert [client.get("/x").status_code for _ in range(2)] == [200, 429]
    assert not caplog.records


# ─── client IP behind the proxy ───────────────────────────────────────────────

def _xff(client, value):
    return client.get(PING, headers={"X-Forwarded-For": value})


def test_the_client_ip_is_the_address_the_proxy_appended_not_what_the_client_claimed(client, limit):
    limit("RATE_LIMIT_DEFAULT", "1 per minute")
    assert _xff(client, "5.5.5.5, 9.9.9.9").status_code == 200
    # a different forged prefix, same real client: still the same bucket
    assert _xff(client, "6.6.6.6, 9.9.9.9").status_code == 429
    assert _xff(client, "1.2.3.4, 5.5.5.5, 9.9.9.9").status_code == 429
    # a different real client: its own bucket
    assert _xff(client, "5.5.5.5, 8.8.8.8").status_code == 200


def test_without_a_forwarded_header_the_socket_address_is_used(client, limit):
    limit("RATE_LIMIT_DEFAULT", "1 per minute")
    assert _get(client, PING, ip="10.1.1.1").status_code == 200
    assert _get(client, PING, ip="10.1.1.1").status_code == 429
    assert _get(client, PING, ip="10.1.1.2").status_code == 200



# ─── auth routes ──────────────────────────────────────────────────────────────

LOGIN = "/api/v1/auth/login"
OFF = "1000000 per minute"


def _login(client, email="who@example.com", ip="10.2.0.1", body=None, **kw):
    payload = {"email": email, "password": "Wrong-pass-1", "role": "candidate"} if body is None else body
    return client.post(LOGIN, json=payload, environ_overrides={"REMOTE_ADDR": ip}, **kw)


@pytest.fixture()
def only_login_limit(limit):
    """Lower one login limit and leave the other two out of the way."""
    def _set(which, value):
        for name in ("RATE_LIMIT_LOGIN_IP", "RATE_LIMIT_LOGIN_IP_EMAIL", "RATE_LIMIT_LOGIN_EMAIL"):
            limit(name, OFF)
        limit(which, value)
    return _set


def test_login_is_limited_per_ip_whatever_the_email(client, only_login_limit):
    only_login_limit("RATE_LIMIT_LOGIN_IP", "3 per minute")
    codes = [_login(client, email=f"user{n}@example.com").status_code for n in range(4)]
    assert codes == [401, 401, 401, 429]
    assert _login(client, email="user0@example.com", ip="10.2.0.2").status_code == 401


def test_login_is_limited_per_ip_and_email(client, only_login_limit):
    only_login_limit("RATE_LIMIT_LOGIN_IP_EMAIL", "2 per minute")
    assert [_login(client).status_code for _ in range(3)] == [401, 401, 429]
    assert _login(client, email="other@example.com").status_code == 401     # same IP, other email
    assert _login(client, ip="10.2.0.2").status_code == 401                 # same email, other IP


def test_the_email_in_the_limit_key_ignores_case_and_surrounding_space(client, only_login_limit):
    only_login_limit("RATE_LIMIT_LOGIN_IP_EMAIL", "2 per minute")
    assert _login(client, email="Who@Example.com").status_code == 401
    assert _login(client, email="  who@example.com ").status_code == 401
    assert _login(client, email="WHO@EXAMPLE.COM").status_code == 429


def test_one_email_is_limited_across_many_ips(client, only_login_limit):
    only_login_limit("RATE_LIMIT_LOGIN_EMAIL", "2 per hour")
    assert [_login(client, ip=f"10.3.0.{n}").status_code for n in range(3)] == [401, 401, 429]
    assert _login(client, email="other@example.com", ip="10.3.0.9").status_code == 401


@pytest.mark.parametrize("make", [
    lambda c, **k: c.post(LOGIN, data="not json at all", content_type="text/plain", **k),
    lambda c, **k: c.post(LOGIN, data="{broken", content_type="application/json", **k),
    lambda c, **k: c.post(LOGIN, json=["a", "list"], **k),
    lambda c, **k: c.post(LOGIN, json={"email": 12345, "password": "x", "role": "candidate"}, **k),
    lambda c, **k: c.post(LOGIN, json={"password": "x", "role": "candidate"}, **k),
    lambda c, **k: c.post(LOGIN, json={"email": "   "}, **k),
    lambda c, **k: c.post(LOGIN, **k),
])
def test_an_unusable_login_body_never_breaks_the_key_and_counts_against_the_ip(
    client, only_login_limit, make
):
    only_login_limit("RATE_LIMIT_LOGIN_IP_EMAIL", "2 per minute")
    env = {"environ_overrides": {"REMOTE_ADDR": "10.4.0.1"}}
    statuses = [make(client, **env).status_code for _ in range(3)]
    assert 500 not in statuses
    assert statuses[2] == 429
    assert make(client, environ_overrides={"REMOTE_ADDR": "10.4.0.2"}).status_code != 429


def test_registration_is_limited_per_ip_across_both_account_types(client, limit):
    limit("RATE_LIMIT_REGISTER", "2 per hour")
    ip = {"REMOTE_ADDR": "10.5.0.1"}
    first = client.post("/api/v1/auth/register/candidate", json={}, environ_overrides=ip)
    second = client.post("/api/v1/auth/register/recruiter", json={}, environ_overrides=ip)
    third = client.post("/api/v1/auth/register/candidate", json={}, environ_overrides=ip)
    assert (first.status_code, second.status_code) == (400, 400)
    assert third.status_code == 429
    other_ip = client.post("/api/v1/auth/register/candidate", json={}, environ_overrides={"REMOTE_ADDR": "10.5.0.2"})
    assert other_ip.status_code == 400


def test_refresh_is_limited_per_ip(client, limit):
    limit("RATE_LIMIT_REFRESH", "2 per minute")
    ip = {"REMOTE_ADDR": "10.6.0.1"}
    codes = [client.post("/api/v1/auth/refresh", environ_overrides=ip).status_code for _ in range(3)]
    assert codes[:2] == [401, 401]
    assert codes[2] == 429
    assert client.post("/api/v1/auth/refresh", environ_overrides={"REMOTE_ADDR": "10.6.0.2"}).status_code == 401


def test_a_correct_login_still_works_below_the_limits(client, db, candidate_a, account_password, limit):
    limit("RATE_LIMIT_LOGIN_IP", "5 per minute")
    r = client.post(LOGIN, json={"email": candidate_a.email, "password": account_password, "role": "candidate"})
    assert r.status_code == 200


# ─── downloads ────────────────────────────────────────────────────────────────

@pytest.fixture()
def downloadable(app, db, tmp_path, monkeypatch, resume_a):
    from app.services.storage_service import LocalStorageBackend

    monkeypatch.setitem(app.config, "STORAGE_PROVIDER", "local")
    monkeypatch.setitem(app.config, "UPLOAD_FOLDER", str(tmp_path / "uploads"))
    resume_a.storage_key = LocalStorageBackend(str(tmp_path / "uploads")).upload(b"%PDF-1.4 x", "pdf").key
    db.session.commit()
    return f"/api/v1/resumes/{resume_a.id}/download"


def test_downloads_are_limited_per_user(client, limit, downloadable, candidate_a, headers_for):
    limit("RATE_LIMIT_DOWNLOAD", "2 per minute")
    codes = [client.get(downloadable, headers=headers_for(candidate_a)).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_downloads_by_different_users_do_not_share_a_budget(
    client, db, limit, downloadable, application_a, candidate_a, recruiter_a, headers_for
):
    limit("RATE_LIMIT_DOWNLOAD", "1 per minute")
    assert client.get(downloadable, headers=headers_for(candidate_a)).status_code == 200
    assert client.get(downloadable, headers=headers_for(candidate_a)).status_code == 429
    # recruiter A has an application with this résumé, so is allowed in, with a budget of their own
    assert client.get(downloadable, headers=headers_for(recruiter_a)).status_code == 200


def test_an_anonymous_download_is_401_not_429(client, limit, downloadable):
    limit("RATE_LIMIT_DOWNLOAD", "1 per minute")
    assert [client.get(downloadable).status_code for _ in range(3)] == [401, 401, 401]
