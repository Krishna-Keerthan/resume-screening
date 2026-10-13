"""
Ownership helpers in app.core.security and the AuthError handler.
"""

from types import SimpleNamespace

import pytest

from app.core.security import (
    AuthError,
    assert_can_view_application,
    assert_can_view_score,
    assert_owns,
    assert_recruiter_can_view_resume,
)


# ─── assert_owns ──────────────────────────────────────────────────────────────

def test_assert_owns_passes_for_the_owner():
    assert_owns(SimpleNamespace(candidate_id="u1"), "u1", owner_attr="candidate_id")


def test_assert_owns_compares_ids_as_strings():
    assert_owns(SimpleNamespace(owner=7), "7", owner_attr="owner")


def test_assert_owns_rejects_another_user_with_403():
    with pytest.raises(AuthError) as exc:
        assert_owns(SimpleNamespace(candidate_id="u1"), "u2", owner_attr="candidate_id")
    assert (exc.value.status, exc.value.code) == (403, "FORBIDDEN")


def test_assert_owns_uses_the_custom_message():
    with pytest.raises(AuthError, match="not yours"):
        assert_owns(SimpleNamespace(candidate_id="u1"), "u2", owner_attr="candidate_id", message="not yours")


def test_assert_owns_rejects_a_missing_resource_and_a_missing_attribute():
    with pytest.raises(AuthError):
        assert_owns(None, "u1", owner_attr="candidate_id")
    with pytest.raises(AuthError):
        assert_owns(SimpleNamespace(), "u1", owner_attr="candidate_id")


def test_assert_owns_requires_owner_attr_by_keyword():
    with pytest.raises(TypeError):
        assert_owns(SimpleNamespace(candidate_id="u1"), "u1")
    with pytest.raises(TypeError):
        assert_owns(SimpleNamespace(candidate_id="u1"), "u1", "candidate_id")


# ─── AuthError handler ────────────────────────────────────────────────────────

def test_an_uncaught_auth_error_becomes_a_json_error_response(app):
    with app.test_request_context("/"):
        try:
            raise AuthError("No.", code="FORBIDDEN", status=403)
        except AuthError as exc:
            resp = app.handle_user_exception(exc)

    body, status = resp if isinstance(resp, tuple) else (resp, resp.status_code)
    assert status == 403
    payload = body.get_json() if hasattr(body, "get_json") else body
    assert payload == {"success": False, "error": {"error_code": "FORBIDDEN", "message": "No."}}


# ─── Applications ─────────────────────────────────────────────────────────────

def test_application_is_visible_to_its_candidate_and_to_the_jobs_recruiter(
    application_a, candidate_a, recruiter_a
):
    assert_can_view_application(application_a, candidate_a.id, "candidate")
    assert_can_view_application(application_a, recruiter_a.id, "recruiter")


def test_application_is_hidden_from_everyone_else(
    application_a, candidate_b, recruiter_b, candidate_a, recruiter_a
):
    for user_id, role in (
        (candidate_b.id, "candidate"),
        (recruiter_b.id, "recruiter"),
        # an id is only meaningful together with its role
        (recruiter_a.id, "candidate"),
        (candidate_a.id, "recruiter"),
        (candidate_a.id, "admin"),
    ):
        with pytest.raises(AuthError) as exc:
            assert_can_view_application(application_a, user_id, role)
        assert exc.value.status == 403


def test_a_missing_application_is_forbidden(candidate_a):
    with pytest.raises(AuthError):
        assert_can_view_application(None, candidate_a.id, "candidate")


# ─── ATS scores ───────────────────────────────────────────────────────────────

@pytest.fixture()
def score_a(db, resume_a, job_a):
    from app.models.ats_score import AtsScore
    s = AtsScore(resume_id=resume_a.id, job_id=job_a.id)
    s.save()
    db.session.flush()
    return s


def test_score_is_visible_to_the_resume_owner_and_the_jobs_recruiter(
    score_a, candidate_a, recruiter_a
):
    assert_can_view_score(score_a, candidate_a.id, "candidate")
    assert_can_view_score(score_a, recruiter_a.id, "recruiter")


def test_score_is_hidden_from_everyone_else(score_a, candidate_b, recruiter_b):
    for user_id, role in ((candidate_b.id, "candidate"), (recruiter_b.id, "recruiter")):
        with pytest.raises(AuthError) as exc:
            assert_can_view_score(score_a, user_id, role)
        assert exc.value.status == 403


# ─── Recruiter access to a résumé ─────────────────────────────────────────────

def test_recruiter_can_view_a_resume_attached_to_an_application_to_their_job(
    application_a, resume_a, recruiter_a
):
    assert_recruiter_can_view_resume(resume_a, recruiter_a.id)


def test_recruiter_cannot_view_a_resume_without_an_application_to_their_job(
    application_a, resume_a, resume_b, recruiter_a, recruiter_b
):
    with pytest.raises(AuthError) as exc:
        assert_recruiter_can_view_resume(resume_a, recruiter_b.id)
    assert exc.value.status == 403
    # recruiter A has an application, but it carries résumé A, not B
    with pytest.raises(AuthError):
        assert_recruiter_can_view_resume(resume_b, recruiter_a.id)
