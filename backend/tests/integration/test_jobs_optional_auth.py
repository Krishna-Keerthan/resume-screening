"""
GET /jobs and GET /jobs/<id> accept an optional token. A valid recruiter
token widens what they see to their own non-active jobs; a missing, garbage,
expired, wrong-type or dead-account token is treated as anonymous (never a
401 or 500, and never any drafts).
"""
import time

import jwt
import pytest
from flask import current_app

from app.models.enums import JobStatus

BASE = "/api/v1/jobs"


def _forged(app, **claims):
    payload = {"type": "access", "iat": int(time.time()), "exp": int(time.time()) + 600, **claims}
    with app.app_context():
        return jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")


@pytest.fixture()
def draft_a(db, job_a):
    job_a.status = JobStatus.DRAFT.value
    db.session.commit()
    return job_a


@pytest.fixture()
def draft_b(db, job_b):
    job_b.status = JobStatus.DRAFT.value
    db.session.commit()
    return job_b


@pytest.fixture()
def bad_token_headers(app, recruiter_a):
    """Tokens that are not usable, each of which names recruiter A (or nobody)."""
    return {
        "garbage":        {"Authorization": "Bearer not-a-jwt"},
        "empty":          {"Authorization": "Bearer "},
        "wrong scheme":   {"Authorization": "Basic abc"},
        "expired":        {"Authorization": "Bearer " + _forged(app, sub=recruiter_a.id, role="recruiter",
                                                                exp=int(time.time()) - 60)},
        "refresh type":   {"Authorization": "Bearer " + _forged(app, sub=recruiter_a.id, role="recruiter",
                                                                type="refresh")},
        "bad signature":  {"Authorization": "Bearer " + jwt.encode(
                              {"sub": recruiter_a.id, "role": "recruiter", "type": "access",
                               "exp": int(time.time()) + 600}, "other-secret", algorithm="HS256")},
        "unknown user":   {"Authorization": "Bearer " + _forged(app, sub="no-such-id", role="recruiter")},
    }


class TestListJobsOptionalAuth:
    def test_anonymous_gets_active_jobs_and_no_drafts(self, client, db, sample_job, draft_a, anon):
        for query in ("", "?status=draft"):
            r = client.get(f"{BASE}/{query}", headers=anon)
            assert r.status_code == 200
            ids = [j["id"] for j in r.get_json()["data"]]
            assert sample_job.id in ids
            assert draft_a.id not in ids

    def test_recruiter_sees_own_drafts_and_not_other_recruiters_drafts(
        self, client, db, draft_a, draft_b, recruiter_a, recruiter_b, headers_for
    ):
        ids_a = [j["id"] for j in client.get(f"{BASE}/?status=draft", headers=headers_for(recruiter_a)).get_json()["data"]]
        ids_b = [j["id"] for j in client.get(f"{BASE}/?status=draft", headers=headers_for(recruiter_b)).get_json()["data"]]
        assert ids_a == [draft_a.id]
        assert ids_b == [draft_b.id]

    def test_recruiter_default_list_is_active_jobs_only(
        self, client, db, sample_job, draft_a, recruiter_a, headers_for
    ):
        ids = [j["id"] for j in client.get(f"{BASE}/", headers=headers_for(recruiter_a)).get_json()["data"]]
        assert sample_job.id in ids
        assert draft_a.id not in ids

    def test_unusable_tokens_are_anonymous(self, client, db, sample_job, draft_a, bad_token_headers):
        for label, headers in bad_token_headers.items():
            for query in ("", "?status=draft"):
                r = client.get(f"{BASE}/{query}", headers=headers)
                assert r.status_code == 200, (label, query, r.get_json())
                ids = [j["id"] for j in r.get_json()["data"]]
                assert sample_job.id in ids, (label, query)
                assert draft_a.id not in ids, (label, query)

    def test_deleted_or_deactivated_recruiter_is_anonymous(
        self, client, db, draft_a, recruiter_a, headers_for
    ):
        headers = headers_for(recruiter_a)
        recruiter_a.is_active = False
        db.session.commit()
        ids = [j["id"] for j in client.get(f"{BASE}/?status=draft", headers=headers).get_json()["data"]]
        assert draft_a.id not in ids

        recruiter_a.is_active = True
        recruiter_a.is_deleted = True
        db.session.commit()
        ids = [j["id"] for j in client.get(f"{BASE}/?status=draft", headers=headers).get_json()["data"]]
        assert draft_a.id not in ids


class TestGetJobOptionalAuth:
    def test_anonymous_gets_active_job_but_404_for_draft(self, client, db, sample_job, draft_a, anon):
        assert client.get(f"{BASE}/{sample_job.id}", headers=anon).status_code == 200
        assert client.get(f"{BASE}/{draft_a.id}", headers=anon).status_code == 404

    def test_recruiter_sees_own_draft_but_not_another_recruiters(
        self, client, db, draft_a, draft_b, recruiter_a, headers_for
    ):
        assert client.get(f"{BASE}/{draft_a.id}", headers=headers_for(recruiter_a)).status_code == 200
        assert client.get(f"{BASE}/{draft_b.id}", headers=headers_for(recruiter_a)).status_code == 404

    def test_unusable_tokens_are_anonymous(self, client, db, sample_job, draft_a, bad_token_headers):
        for label, headers in bad_token_headers.items():
            assert client.get(f"{BASE}/{sample_job.id}", headers=headers).status_code == 200, label
            r = client.get(f"{BASE}/{draft_a.id}", headers=headers)
            assert r.status_code == 404, label
            assert r.get_json()["error"]["error_code"] == "JOB_NOT_FOUND", label

    def test_deleted_or_deactivated_recruiter_cannot_read_their_own_draft(
        self, client, db, draft_a, recruiter_a, headers_for
    ):
        headers = headers_for(recruiter_a)
        recruiter_a.is_active = False
        db.session.commit()
        assert client.get(f"{BASE}/{draft_a.id}", headers=headers).status_code == 404

        recruiter_a.is_active = True
        recruiter_a.is_deleted = True
        db.session.commit()
        assert client.get(f"{BASE}/{draft_a.id}", headers=headers).status_code == 404
