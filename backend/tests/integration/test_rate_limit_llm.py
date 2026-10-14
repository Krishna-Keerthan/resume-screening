"""
Routes that can call Groq share one per-user budget (RATE_LIMIT_LLM), applied
after authentication: an anonymous caller gets 401, never 429.
"""
from types import SimpleNamespace

import pytest

# name -> (method, role, url, json)
LLM_ROUTES = {
    "create_job":         ("POST", "recruiter", lambda f: "/api/v1/jobs", {}),
    "enhance_job":        ("POST", "recruiter", lambda f: f"/api/v1/jobs/{f.job_a.id}/enhance", {}),
    "score_application":  ("POST", "recruiter", lambda f: f"/api/v1/applications/{f.application_a.id}/score", {}),
    "application_summary": ("GET", "recruiter", lambda f: f"/api/v1/applications/{f.application_a.id}/ai-summary", None),
    "create_application": ("POST", "candidate", lambda f: "/api/v1/applications/", {}),
    "analyze_resume":     ("POST", "candidate", lambda f: f"/api/v1/resumes/{f.resume_a.id}/analyze", {}),
    "generate_summary":   ("POST", "candidate", lambda f: f"/api/v1/resumes/{f.resume_a.id}/generate-summary", {}),
    "rewrite_suggestions": ("POST", "candidate", lambda f: f"/api/v1/resumes/{f.resume_a.id}/rewrite-suggestions", {}),
    "score_match":        ("POST", "candidate", lambda f: "/api/v1/scores/match", {}),
}
ROUTE_IDS = list(LLM_ROUTES)


@pytest.fixture()
def world(db, candidate_a, candidate_b, recruiter_a, recruiter_b, job_a, resume_a, application_a, headers_for, client):
    users = {"candidate": (candidate_a, candidate_b), "recruiter": (recruiter_a, recruiter_b)}
    return SimpleNamespace(
        job_a=job_a, resume_a=resume_a, application_a=application_a, users=users,
        headers_for=headers_for, client=client,
    )


def _call(world, route, user, headers=None):
    method, _role, url, body = LLM_ROUTES[route]
    return world.client.open(url(world), method=method, json=body,
                             headers=world.headers_for(user) if headers is None else headers)


@pytest.mark.parametrize("route", ROUTE_IDS)
def test_the_llm_budget_is_enforced_per_user(world, limit, route):
    limit("RATE_LIMIT_LLM", "2 per minute")
    owner = world.users[LLM_ROUTES[route][1]][0]
    codes = [_call(world, route, owner).status_code for _ in range(3)]
    assert 429 not in codes[:2]
    assert codes[2] == 429


@pytest.mark.parametrize("route", ROUTE_IDS)
def test_two_users_on_the_same_ip_have_separate_budgets(world, limit, route):
    limit("RATE_LIMIT_LLM", "1 per minute")
    first, second = world.users[LLM_ROUTES[route][1]]
    _call(world, route, first)
    assert _call(world, route, first).status_code == 429
    assert _call(world, route, second).status_code != 429


@pytest.mark.parametrize("route", ROUTE_IDS)
def test_an_anonymous_call_is_401_not_429_and_uses_up_no_budget(world, limit, route):
    limit("RATE_LIMIT_LLM", "1 per minute")
    codes = [_call(world, route, None, headers={}).status_code for _ in range(4)]
    assert codes == [401] * 4
    owner = world.users[LLM_ROUTES[route][1]][0]
    assert _call(world, route, owner).status_code != 429


def test_the_budget_is_shared_by_all_llm_routes(world, limit):
    limit("RATE_LIMIT_LLM", "2 per minute")
    me = world.users["candidate"][0]
    assert _call(world, "analyze_resume", me).status_code != 429
    assert _call(world, "generate_summary", me).status_code != 429
    assert _call(world, "rewrite_suggestions", me).status_code == 429
    assert _call(world, "score_match", me).status_code == 429


def test_both_parts_of_the_default_llm_limit_apply(world, limit):
    limit("RATE_LIMIT_LLM", "100 per minute;1 per day")
    me = world.users["candidate"][0]
    assert _call(world, "analyze_resume", me).status_code != 429
    assert _call(world, "analyze_resume", me).status_code == 429


def test_score_preview_never_reaches_groq_and_is_not_under_the_llm_limit(
    client, db, limit, resume_a, job_a, candidate_a, headers_for, mock_services
):
    from app.services.explainability_engine import ExplanationResult

    mock_services.groq.available = True
    mock_services.ats_scorer.score_raw.return_value = {
        "final_score": 0.7, "semantic_score": 0.0, "keyword_score": 0.8, "experience_score": 0.7,
        "section_quality_score": 0.6, "semantic_available": False, "semantic_component_scores": {},
        "weights_used": {"semantic": 0.4, "keyword": 0.35, "experience": 0.15, "section": 0.1},
    }
    mock_services.explainability.explain.return_value = ExplanationResult()
    limit("RATE_LIMIT_LLM", "1 per minute")
    url = f"/api/v1/resumes/{resume_a.id}/score-preview?job_id={job_a.id}"

    codes = [client.get(url, headers=headers_for(candidate_a)).status_code for _ in range(5)]

    assert codes == [200] * 5
    assert mock_services.explainability.explain.call_args.kwargs["use_llm"] is False
    assert mock_services.groq.method_calls == []
