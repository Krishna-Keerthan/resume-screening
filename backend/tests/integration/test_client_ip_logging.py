"""
The client IP is logged, at INFO, on exactly two events: a 429 and a failed login. Nothing
else about the caller goes with it: no email, no password, no token.
"""
import logging

import pytest

LOGIN = "/api/v1/auth/login"
_IP = {"REMOTE_ADDR": "203.0.113.7"}


def _records(caplog, message):
    return [r for r in caplog.records if r.getMessage() == message]


def _extras(record):
    standard = set(logging.LogRecord("n", 0, "p", 0, "m", None, None).__dict__) | {"request_id", "message", "asctime"}
    return {k: v for k, v in record.__dict__.items() if k not in standard}


def test_a_429_logs_the_ip_path_and_method_at_info(client, limit, caplog):
    caplog.set_level(logging.INFO)
    limit("RATE_LIMIT_DEFAULT", "1 per minute")
    client.get("/api/v1/jobs", environ_overrides=_IP)

    assert client.get("/api/v1/jobs", environ_overrides=_IP).status_code == 429

    (record,) = _records(caplog, "Rate limit exceeded")
    assert record.levelno == logging.INFO
    assert _extras(record) == {"ip": "203.0.113.7", "method": "GET", "path": "/api/v1/jobs"}


@pytest.mark.parametrize("role", ["candidate", "recruiter"])
def test_a_failed_login_logs_only_the_ip(client, db, candidate_a, caplog, role):
    caplog.set_level(logging.INFO)
    body = {"email": candidate_a.email, "password": "wrong-Password-1", "role": role}

    assert client.post(LOGIN, json=body, environ_overrides=_IP).status_code == 401

    (record,) = _records(caplog, "Login failed")
    assert record.levelno == logging.INFO
    assert _extras(record) == {"ip": "203.0.113.7"}
    assert candidate_a.email not in caplog.text and "wrong-Password-1" not in caplog.text


def test_an_unknown_account_is_logged_the_same_way(client, db, caplog):
    caplog.set_level(logging.INFO)
    body = {"email": "nobody@example.com", "password": "SecureP@ss1", "role": "candidate"}

    client.post(LOGIN, json=body, environ_overrides=_IP)

    (record,) = _records(caplog, "Login failed")
    assert _extras(record) == {"ip": "203.0.113.7"}
    assert "nobody@example.com" not in caplog.text


def test_a_successful_login_logs_no_ip(client, db, candidate_a, account_password, caplog):
    caplog.set_level(logging.INFO)
    body = {"email": candidate_a.email, "password": account_password, "role": "candidate"}

    assert client.post(LOGIN, json=body, environ_overrides=_IP).status_code == 200

    assert "203.0.113.7" not in caplog.text
    assert not _records(caplog, "Login failed")


def test_an_ordinary_request_logs_no_ip_at_info(client, caplog):
    caplog.set_level(logging.INFO)

    client.get("/api/v1/health", environ_overrides=_IP)

    assert "203.0.113.7" not in caplog.text
