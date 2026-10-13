"""
Self routes (/candidates/<id>/..., /recruiters/<id>/...): a valid token for a
different id is 403, whether that id belongs to another user or to nobody.
"""
import io
import uuid

import pytest

C = "/api/v1/candidates"
R = "/api/v1/recruiters"

_PDF = lambda: {"file": (io.BytesIO(b"%PDF-1.4 x"), "resume.pdf", "application/pdf")}  # noqa: E731

# (method, path template, kwargs for the request)
CANDIDATE_ROUTES = [
    ("GET",    C + "/{id}",                {}),
    ("PATCH",  C + "/{id}",                {"json": {"headline": "x"}}),
    ("DELETE", C + "/{id}",                {}),
    ("GET",    C + "/{id}/resumes",        {}),
    ("POST",   C + "/{id}/resumes",        {"data": _PDF, "content_type": "multipart/form-data"}),
    ("GET",    C + "/{id}/skill-gaps",     {}),
    ("GET",    C + "/{id}/win-rate-insights", {}),
]
RECRUITER_ROUTES = [
    ("GET",    R + "/{id}",                {}),
    ("PATCH",  R + "/{id}",                {"json": {"industry": "x"}}),
    ("DELETE", R + "/{id}",                {}),
    ("GET",    R + "/{id}/jobs",           {}),
    ("GET",    R + "/{id}/analytics",      {}),
]


def _call(client, method, template, kwargs, target_id, headers):
    kwargs = {k: (v() if callable(v) else v) for k, v in kwargs.items()}
    return client.open(template.format(id=target_id), method=method, headers=headers, **kwargs)


@pytest.mark.parametrize("method, template, kwargs", CANDIDATE_ROUTES)
@pytest.mark.parametrize("target", ["another_user", "nobody"])
def test_a_candidate_token_with_a_different_id_is_403(
    client, db, candidate_a, candidate_b, headers_for, mock_services, method, template, kwargs, target
):
    target_id = candidate_b.id if target == "another_user" else str(uuid.uuid4())
    r = _call(client, method, template, kwargs, target_id, headers_for(candidate_a))
    assert r.status_code == 403, r.get_json()


@pytest.mark.parametrize("method, template, kwargs", RECRUITER_ROUTES)
@pytest.mark.parametrize("target", ["another_user", "nobody"])
def test_a_recruiter_token_with_a_different_id_is_403(
    client, db, recruiter_a, recruiter_b, headers_for, mock_services, method, template, kwargs, target
):
    target_id = recruiter_b.id if target == "another_user" else str(uuid.uuid4())
    r = _call(client, method, template, kwargs, target_id, headers_for(recruiter_a))
    assert r.status_code == 403, r.get_json()


@pytest.mark.parametrize("target", ["another_user", "nobody"])
def test_a_rejected_delete_leaves_the_other_account_alone(
    client, db, candidate_a, candidate_b, headers_for, target
):
    target_id = candidate_b.id if target == "another_user" else str(uuid.uuid4())
    client.delete(f"{C}/{target_id}", headers=headers_for(candidate_a))
    db.session.refresh(candidate_a)
    db.session.refresh(candidate_b)
    assert candidate_a.is_deleted is False and candidate_b.is_deleted is False
