"""
The temporary proxy-chain log line (LOG_PROXY_CHAIN): off by default, and when
on it records only IP addresses, never credentials.
"""
import logging

LOGIN = "/api/v1/auth/login"
SECRET_COOKIE = "refresh_token=cookie-secret-value"
SECRET_BEARER = "Bearer bearer-secret-value"
CHAIN = "203.0.113.7, 198.51.100.2"


def _post_login(client):
    return client.post(
        LOGIN,
        json={"email": "nobody@example.com", "password": "x" * 12, "role": "candidate"},
        headers={"X-Forwarded-For": CHAIN, "Cookie": SECRET_COOKIE, "Authorization": SECRET_BEARER},
    )


def _chain_records(caplog):
    return [r for r in caplog.records if "proxy chain" in r.getMessage().lower()]


def test_the_log_is_off_by_default(app, client, caplog):
    assert app.config["LOG_PROXY_CHAIN"] is False
    with caplog.at_level(logging.DEBUG):
        _post_login(client)
    assert not _chain_records(caplog)


def test_when_on_it_logs_the_chain_the_hops_and_the_resulting_address(app, client, caplog, monkeypatch):
    monkeypatch.setitem(app.config, "LOG_PROXY_CHAIN", True)
    with caplog.at_level(logging.DEBUG):
        _post_login(client)

    (record,) = _chain_records(caplog)
    assert record.levelno == logging.WARNING
    assert record.forwarded_for == CHAIN
    assert record.trusted_hops == 2
    assert record.client_ip == "203.0.113.7"


def test_it_never_logs_cookies_or_tokens(app, client, caplog, monkeypatch):
    monkeypatch.setitem(app.config, "LOG_PROXY_CHAIN", True)
    with caplog.at_level(logging.DEBUG):
        _post_login(client)

    text = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in _chain_records(caplog))
    assert "cookie-secret-value" not in text
    assert "bearer-secret-value" not in text


def test_it_only_logs_the_login_route(app, client, caplog, monkeypatch):
    monkeypatch.setitem(app.config, "LOG_PROXY_CHAIN", True)
    with caplog.at_level(logging.DEBUG):
        client.get("/api/v1/jobs", headers={"X-Forwarded-For": CHAIN})
    assert not _chain_records(caplog)
