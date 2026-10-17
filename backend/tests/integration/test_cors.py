"""CORS preflight responses."""

ORIGIN = "http://localhost:3000"


def _preflight(client, origin=ORIGIN):
    return client.options(
        "/api/v1/jobs",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )


def test_preflight_tells_browsers_how_long_to_cache_it(app, client):
    r = _preflight(client)

    assert r.headers["Access-Control-Allow-Origin"] == ORIGIN
    assert r.headers["Access-Control-Max-Age"] == str(app.config["CORS_MAX_AGE"])


def test_preflight_from_an_unlisted_origin_gets_no_allow_origin(client):
    r = _preflight(client, origin="https://evil.example")

    assert "Access-Control-Allow-Origin" not in r.headers
