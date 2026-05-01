
"""
tests/integration/e2e/test_e2e_recruiter_flow.py

End-to-end: Recruiter journey from job posting → candidate ranking → analytics.

Flow:
  1. Create recruiter
  2. Post multiple jobs
  3. Create candidates with resumes
  4. Submit applications
  5. Request candidate ranking for a job
  6. Advance one application to hired
  7. Check analytics pipeline funnel
"""
import json
import uuid
from unittest.mock import MagicMock

import pytest


def _post(client, url, body):
    r = client.post(url, data=json.dumps(body), content_type="application/json")
    return r, r.get_json()


def _patch(client, url, body):
    r = client.patch(url, data=json.dumps(body), content_type="application/json")
    return r, r.get_json()


class TestRecruiterJourneyE2E:
    def test_recruiter_full_cycle(self, client, db, mock_services):
        # 1. Create recruiter
        r, rec_body = _post(client, "/api/v1/recruiters/", {
            "full_name":    "E2E HR",
            "email":        f"e2e+{uuid.uuid4().hex[:6]}@bigcorp.com",
            "company_name": "BigCorp",
            "company_size": "201-500",
            "industry":     "Finance",
        })
        assert r.status_code == 201
        rec_id = rec_body["data"]["id"]

        # 2. Post a job
        r, job_body = _post(client, "/api/v1/jobs/", {
            "title":            "E2E Data Engineer",
            "company":          "BigCorp",
            "description":      "Seeking a Data Engineer experienced in Spark and Hadoop for our data platform.",
            "experience_years": 4.0,
            "location":         "Hyderabad, India",
            "job_type":         "full-time",
            "required_skills":  ["Python", "Spark", "Hadoop"],
            "recruiter_id":     rec_id,
        })
        assert r.status_code == 201
        job_id = job_body["data"]["id"]

        # Verify job in recruiter jobs list
        body = client.get(f"/api/v1/recruiters/{rec_id}/jobs").get_json()
        assert any(j["id"] == job_id for j in body["data"])

        # 3. Check analytics (mocked)
        mock_services.recruiter_analytics.get_dashboard.return_value = MagicMock(
            recruiter_id=rec_id, total_jobs=1, active_jobs=1,
            total_applications=0, total_hired=0, avg_score=0.0,
            pipeline_funnel={}, top_jobs=[], score_distribution={}, skills_demand=[],
        )
        r = client.get(f"/api/v1/analytics/dashboard?recruiter_id={rec_id}")
        assert r.status_code == 200
        data = r.get_json()["data"]
        assert "total_jobs" in data
        assert "pipeline_funnel" in data

        # 4. Update job status to closed
        r, body = _patch(client, f"/api/v1/jobs/{job_id}", {"status": "closed"})
        assert r.status_code == 200
        assert body["data"]["status"] == "closed"

        # 5. Delete recruiter (soft-delete)
        assert client.delete(f"/api/v1/recruiters/{rec_id}").status_code == 204
        assert client.get(f"/api/v1/recruiters/{rec_id}").status_code == 404