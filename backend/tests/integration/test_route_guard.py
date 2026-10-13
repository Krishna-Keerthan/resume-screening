"""
Regression guard for Phase 1: every API route must be behind @require_auth
unless it is on the explicit allowlist below.

Adding a public route means adding it here, on purpose, in review.
"""
import pytest
from flask import Flask

from app.core.security import require_auth

PREFIX = "/api/v1"

# (method, rule) of the routes that are deliberately reachable without a token.
PUBLIC_ROUTES = frozenset({
    # sign-up and session establishment
    ("POST", f"{PREFIX}/auth/register/candidate"),
    ("POST", f"{PREFIX}/auth/register/recruiter"),
    ("POST", f"{PREFIX}/auth/login"),
    ("POST", f"{PREFIX}/auth/refresh"),      # authenticated by the refresh cookie
    # liveness / readiness probes
    ("GET", f"{PREFIX}/health"),
    ("GET", f"{PREFIX}/health/ready"),
    ("GET", f"{PREFIX}/health/services"),
    # the public job board (non-active jobs are hidden inside the handlers)
    ("GET", f"{PREFIX}/jobs"),
    ("GET", f"{PREFIX}/jobs/<job_id>"),
})

_IGNORED_METHODS = {"HEAD", "OPTIONS"}


def api_routes(flask_app):
    """{(method, rule): view_function} for every API route."""
    routes = {}
    for rule in flask_app.url_map.iter_rules():
        if not rule.rule.startswith(PREFIX):
            continue
        for method in rule.methods - _IGNORED_METHODS:
            routes[(method, rule.rule.rstrip("/") or rule.rule)] = flask_app.view_functions[rule.endpoint]
    return routes


def unguarded_routes(flask_app, allowlist=PUBLIC_ROUTES):
    """Routes with neither @require_auth nor an allowlist entry."""
    return sorted(
        route for route, view in api_routes(flask_app).items()
        if route not in allowlist and not getattr(view, "requires_auth", False)
    )


# ─── The guard on the real app ────────────────────────────────────────────────

def test_every_api_route_requires_auth_or_is_allowlisted(app):
    assert unguarded_routes(app) == []


def test_the_allowlist_has_no_stale_entries(app):
    assert PUBLIC_ROUTES <= set(api_routes(app)), sorted(PUBLIC_ROUTES - set(api_routes(app)))


def test_allowlisted_routes_are_not_marked_as_protected_by_accident(app):
    routes = api_routes(app)
    # public job reads must stay readable without a token
    assert not getattr(routes[("GET", f"{PREFIX}/jobs")], "requires_auth", False)
    assert not getattr(routes[("GET", f"{PREFIX}/jobs/<job_id>")], "requires_auth", False)


def test_the_api_has_routes_to_check(app):
    assert len(api_routes(app)) > 40


# ─── The checker itself ───────────────────────────────────────────────────────

def _throwaway_app():
    probe = Flask("probe")

    @probe.get(f"{PREFIX}/open")
    def open_route():
        return "x"

    @probe.get(f"{PREFIX}/guarded")
    @require_auth()
    def guarded_route():
        return "x"

    @probe.get(f"{PREFIX}/guarded-under-another-decorator")
    @require_auth("recruiter")
    def another():
        return "x"

    @probe.get("/not-the-api")
    def elsewhere():
        return "x"

    return probe


def test_the_checker_flags_a_route_without_auth():
    assert unguarded_routes(_throwaway_app(), allowlist=frozenset()) == [("GET", f"{PREFIX}/open")]


def test_the_checker_accepts_an_allowlisted_route():
    allowlist = frozenset({("GET", f"{PREFIX}/open")})
    assert unguarded_routes(_throwaway_app(), allowlist=allowlist) == []


# ─── Routing details the frontend relies on ───────────────────────────────────

@pytest.mark.parametrize("url", ["/api/v1/jobs", "/api/v1/jobs/"])
def test_job_list_works_with_and_without_a_trailing_slash(client, url):
    assert client.get(url).status_code == 200


@pytest.mark.parametrize("url", ["/api/v1/applications", "/api/v1/applications/"])
def test_applications_list_works_with_and_without_a_trailing_slash(client, url, candidate_a, headers_for):
    assert client.get(url, headers=headers_for(candidate_a)).status_code == 200
