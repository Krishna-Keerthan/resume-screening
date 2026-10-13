"""
tests/integration/e2e/test_e2e_candidate_flow.py

End-to-end: a recruiter and a candidate each register through /auth/register/*
and use only the tokens they get back. Only the file storage, the résumé
parser and the scorer are stubbed.

Flow:
  1. Recruiter and candidate register
  2. Recruiter posts a job
  3. Candidate uploads a résumé and applies
  4. Recruiter advances the application: applied → reviewed → shortlisted
  5. Candidate sees the stage; the recruiter can read the applicant's profile
  6. Candidate deletes their account; the recruiter can no longer read it
"""
import io
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

API = "/api/v1"
PASSWORD = "SecureP@ss1"


def _bearer(register_response):
    return {"Authorization": f"Bearer {register_response.get_json()['data']['access_token']}"}


@pytest.fixture()
def stub_storage_and_parser(mock_services):
    stored = SimpleNamespace(url="stub://resume.pdf", public_key="stub-key", size_kb=1, provider="stub")
    mock_services.resume_parser.parse_bytes.return_value = SimpleNamespace(
        success=False, parse_error="stubbed"
    )
    mock_services.ats_scorer.score_resume_job.return_value.error = None
    mock_services.ats_scorer.score_resume_job.return_value.final_score = 0.82
    mock_services.ats_scorer.score_resume_job.return_value.score_label = "excellent"
    with patch("app.services.storage_service.LocalStorageBackend.upload", return_value=stored):
        yield


class TestCandidateJourneyE2E:
    def test_full_flow(self, client, db, stub_storage_and_parser):
        # 1. Both sides register and keep the tokens they are given
        r = client.post(f"{API}/auth/register/recruiter", json={
            "full_name": "E2E Recruiter", "email": f"e2e_hr+{uuid.uuid4().hex[:6]}@corp.com",
            "password": PASSWORD, "company_name": "E2E Corp", "company_size": "51-200",
            "industry": "Technology",
        })
        assert r.status_code == 201, r.get_json()
        hr = _bearer(r)

        r = client.post(f"{API}/auth/register/candidate", json={
            "full_name": "E2E Jane", "email": f"e2e_jane+{uuid.uuid4().hex[:6]}@example.com",
            "password": PASSWORD, "location": "Mumbai, India",
        })
        assert r.status_code == 201, r.get_json()
        jane = _bearer(r)
        candidate_id = r.get_json()["data"]["user"]["id"]

        # 2. The recruiter posts a job
        r = client.post(f"{API}/jobs/", headers=hr, json={
            "title": "E2E Python Dev", "company": "E2E Corp",
            "description": "Looking for a Python developer with Flask and PostgreSQL experience.",
            "experience_years": 3.0, "location": "Remote", "job_type": "full-time",
            "required_skills": ["Python", "Flask", "PostgreSQL"],
        })
        assert r.status_code == 201, r.get_json()
        job_id = r.get_json()["data"]["id"]

        # 3. The candidate uploads a résumé and applies
        r = client.post(
            f"{API}/candidates/{candidate_id}/resumes", headers=jane,
            data={"file": (io.BytesIO(b"%PDF-1.4 fake resume data"), "resume.pdf", "application/pdf")},
            content_type="multipart/form-data",
        )
        assert r.status_code == 201, r.get_json()
        resume_id = r.get_json()["data"]["id"]

        r = client.post(f"{API}/applications/", headers=jane, json={"job_id": job_id, "resume_id": resume_id})
        assert r.status_code == 201, r.get_json()
        app_id = r.get_json()["data"]["id"]
        assert r.get_json()["data"]["stage"] == "applied"

        # 4. The recruiter advances it; the candidate cannot
        r = client.patch(f"{API}/applications/{app_id}/stage", headers=jane, json={"stage": "reviewed"})
        assert r.status_code == 403
        for stage in ("reviewed", "shortlisted"):
            r = client.patch(f"{API}/applications/{app_id}/stage", headers=hr, json={"stage": stage})
            assert r.status_code == 200, f"Failed at stage={stage}: {r.get_json()}"
            assert r.get_json()["data"]["stage"] == stage

        # 5. Each side sees it through their own token
        mine = client.get(f"{API}/applications/", headers=jane).get_json()["data"]
        assert [(a["id"], a["stage"]) for a in mine] == [(app_id, "shortlisted")]
        for_job = client.get(f"{API}/applications/?job_id={job_id}", headers=hr).get_json()["data"]
        assert [a["id"] for a in for_job] == [app_id]
        assert client.get(f"{API}/candidates/{candidate_id}", headers=hr).status_code == 200

        # 6. The candidate deletes their account
        assert client.delete(f"{API}/candidates/{candidate_id}", headers=jane).status_code == 204
        assert client.get(f"{API}/candidates/{candidate_id}", headers=hr).status_code == 404
        assert client.get(f"{API}/applications/", headers=jane).status_code == 401

    def test_duplicate_application_blocked(self, client, db, mock_services, headers_for,
                                           sample_candidate, sample_job, sample_resume,
                                           sample_application):
        """Second application to same job from same candidate must return 409."""
        mock_services.ats_scorer.score_resume_job.return_value.error = None
        r = client.post(f"{API}/applications/", headers=headers_for(sample_candidate), json={
            "job_id":    sample_application.job_id,
            "resume_id": sample_application.resume_id,
        })
        assert r.status_code == 409

    def test_closed_job_blocks_application(self, client, db, mock_services, headers_for,
                                           sample_candidate, sample_job_closed, sample_resume):
        """Submitting to a closed job must return 422 JOB_NOT_ACTIVE."""
        r = client.post(f"{API}/applications/", headers=headers_for(sample_candidate), json={
            "job_id":    sample_job_closed.id,
            "resume_id": sample_resume.id,
        })
        assert r.status_code == 422
        assert r.get_json()["error"]["error_code"] == "JOB_NOT_ACTIVE"
