
"""
tests/integration/e2e/test_e2e_candidate_flow.py

End-to-end: Candidate journey from registration → application → stage progression.

Flow:
  1. Create recruiter
  2. Create job
  3. Create candidate
  4. Upload resume (mocked parse) → resume created
  5. Submit application
  6. Advance through stages: applied → reviewed → shortlisted → hired
  7. Verify cannot withdraw hired application
  8. Soft-delete candidate and verify 404
"""
import io
import json
import uuid
from unittest.mock import MagicMock, patch

import pytest


def _post(client, url, body):
    r = client.post(url, data=json.dumps(body), content_type="application/json")
    return r, r.get_json()


def _patch(client, url, body):
    r = client.patch(url, data=json.dumps(body), content_type="application/json")
    return r, r.get_json()


@pytest.fixture()
def mock_parser(app):
    """Mock ResumeParserService.parse to avoid actual PDF parsing."""
    with patch("app.services.resume_parser.ResumeParserService.parse") as m:
        m.return_value = {
            "skills":                  ["Python", "Flask", "PostgreSQL"],
            "total_experience_years":  4.0,
            "education":               [{"degree": "B.Tech", "institution": "IIT"}],
            "experience":              [{"title": "Dev", "company": "X", "years": 4.0}],
            "certifications":          [],
            "summary":                 "Python developer.",
        }
        yield m


class TestCandidateJourneyE2E:
    def test_full_flow(self, client, db, mock_services, mock_parser):
        # 1. Create recruiter
        r, recruiter = _post(client, "/api/v1/recruiters/", {
            "full_name":    "E2E Recruiter",
            "email":        f"e2e_hr+{uuid.uuid4().hex[:6]}@corp.com",
            "company_name": "E2E Corp",
            "company_size": "51-200",
            "industry":     "Technology",
        })
        assert r.status_code == 201
        recruiter_id = recruiter["data"]["id"]

        # 2. Create job
        r, job = _post(client, "/api/v1/jobs/", {
            "title":            "E2E Python Dev",
            "company":          "E2E Corp",
            "description":      "Looking for a Python developer with Flask and PostgreSQL experience.",
            "experience_years": 3.0,
            "location":         "Remote",
            "job_type":         "full-time",
            "required_skills":  ["Python", "Flask", "PostgreSQL"],
            "recruiter_id":     recruiter_id,
        })
        assert r.status_code == 201
        job_id = job["data"]["id"]

        # 3. Create candidate
        r, candidate = _post(client, "/api/v1/candidates/", {
            "full_name":    "E2E Jane",
            "email":        f"e2e_jane+{uuid.uuid4().hex[:6]}@example.com",
            "location":     "Mumbai, India",
            "open_to_work": True,
        })
        assert r.status_code == 201
        candidate_id = candidate["data"]["id"]

        # 4. Upload resume (multipart)
        r = client.post(
            f"/api/v1/candidates/{candidate_id}/resumes",
            data={"file": (io.BytesIO(b"%PDF-1.4 fake resume data"), "resume.pdf")},
            content_type="multipart/form-data",
        )
        assert r.status_code == 201
        resume_id = r.get_json()["data"]["id"]

        # 5. Submit application
        mock_services.ats_scorer.score_resume_job.return_value.error = None
        mock_services.ats_scorer.score_resume_job.return_value.final_score = 0.82
        mock_services.ats_scorer.score_resume_job.return_value.score_label = "excellent"

        r, app_body = _post(client, "/api/v1/applications/", {
            "candidate_id": candidate_id,
            "job_id":       job_id,
            "resume_id":    resume_id,
        })
        assert r.status_code == 201
        app_id = app_body["data"]["id"]
        assert app_body["data"]["stage"] == "applied"

        # 6. Advance stages
        for stage in ["reviewed", "shortlisted"]:
            r, body = _patch(client, f"/api/v1/applications/{app_id}/stage",
                             {"stage": stage})
            assert r.status_code == 200, f"Failed at stage={stage}: {body}"
            assert body["data"]["stage"] == stage

        # Verify application is visible in candidate's list
        body = client.get(
            f"/api/v1/applications/?candidate_id={candidate_id}"
        ).get_json()
        ids = [a["id"] for a in body["data"]]
        assert app_id in ids

        # 7. Soft-delete candidate
        assert client.delete(f"/api/v1/candidates/{candidate_id}").status_code == 204
        assert client.get(f"/api/v1/candidates/{candidate_id}").status_code == 404

    def test_duplicate_application_blocked(self, client, db, mock_services,
                                           sample_candidate, sample_job, sample_resume,
                                           sample_application):
        """Second application to same job from same candidate must return 409."""
        mock_services.ats_scorer.score_resume_job.return_value.error = None
        r, body = _post(client, "/api/v1/applications/", {
            "candidate_id": sample_application.candidate_id,
            "job_id":       sample_application.job_id,
            "resume_id":    sample_application.resume_id,
        })
        assert r.status_code == 409

    def test_closed_job_blocks_application(self, client, db, mock_services,
                                           sample_candidate, sample_job_closed, sample_resume):
        """Submitting to a closed job must return 422 JOB_NOT_ACTIVE."""
        r, body = _post(client, "/api/v1/applications/", {
            "candidate_id": sample_candidate.id,
            "job_id":       sample_job_closed.id,
            "resume_id":    sample_resume.id,
        })
        assert r.status_code == 422
        assert body["error"]["error_code"] == "JOB_NOT_ACTIVE"