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


@pytest.fixture(autouse=True)
def _fresh_counters():
    from app.core.extensions import limiter
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture()
def limit(app, monkeypatch):
    def _set(name, value):
        monkeypatch.setitem(app.config, name, value)
    return _set


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
