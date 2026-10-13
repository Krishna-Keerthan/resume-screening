"""
Tests for the Phase 1 auth fixtures in conftest.py (headers_for, check_access
and the candidate_*/recruiter_* actors), so that route tests built on them
can be trusted.
"""

import pytest

from app.core.security import decode_access_token

BASE = "/api/v1/auth"


def test_actors_are_distinct_real_rows(candidate_a, candidate_b, recruiter_a, recruiter_b):
    assert candidate_a.id != candidate_b.id
    assert recruiter_a.id != recruiter_b.id
    for user in (candidate_a, candidate_b, recruiter_a, recruiter_b):
        assert user.password_hash and user.password_hash != "SecureP@ss1"


def test_owned_objects_belong_to_their_owners(
    job_a, job_b, recruiter_a, recruiter_b,
    resume_a, resume_b, candidate_a, candidate_b, application_a,
):
    assert job_a.recruiter_id == recruiter_a.id
    assert job_b.recruiter_id == recruiter_b.id
    assert resume_a.candidate_id == candidate_a.id
    assert resume_b.candidate_id == candidate_b.id
    assert application_a.candidate_id == candidate_a.id
    assert application_a.job_id == job_a.id
    assert application_a.resume_id == resume_a.id


def test_headers_for_matches_real_login_tokens(
    client, headers_for, candidate_a, recruiter_a, account_password
):
    """Fixture-issued tokens must carry the same claims as /auth/login's."""
    for user, role in ((candidate_a, "candidate"), (recruiter_a, "recruiter")):
        r = client.post(f"{BASE}/login", json={
            "email": user.email, "password": account_password, "role": role,
        })
        assert r.status_code == 200, r.get_json()
        real = decode_access_token(r.get_json()["data"]["access_token"])

        fixture_token = headers_for(user)["Authorization"].removeprefix("Bearer ")
        fake = decode_access_token(fixture_token)

        assert set(real) == set(fake)
        assert (fake["sub"], fake["role"], fake["type"]) == (user.id, role, "access")

        me = client.get(f"{BASE}/me", headers=headers_for(user))
        assert me.status_code == 200
        assert me.get_json()["data"]["user"]["id"] == user.id


def test_anon_sends_no_headers(anon):
    assert anon == {}


def test_check_access_passes_on_a_route_that_enforces_ownership(
    check_access, candidate_a, candidate_b
):
    r = check_access(
        "PATCH", f"/api/v1/candidates/{candidate_a.id}",
        owner=candidate_a, other=candidate_b, json={"headline": "Updated"},
    )
    assert r.get_json()["data"]["headline"] == "Updated"


def test_check_access_detects_a_route_that_accepts_anonymous_callers(
    check_access, job_a, recruiter_a, recruiter_b
):
    """GET /jobs/<id> is public today, so the no-token step must fail."""
    with pytest.raises(AssertionError, match="without a token"):
        check_access("GET", f"/api/v1/jobs/{job_a.id}", owner=recruiter_a, other=recruiter_b)
