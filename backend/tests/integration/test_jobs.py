
"""
tests/integration/test_jobs.py

Integration tests for /api/v1/jobs/* endpoints.
"""
import uuid
import pytest

BASE = "/api/v1/jobs"


def _job_payload(**overrides):
    base = {
        "title":            "Backend Developer",
        "company":          "Startup Inc",
        "description":      "We need a backend developer with Python and Django experience for our growing team.",
        "experience_years": 3.0,
        "location":         "Remote",
        "job_type":         "full-time",
        "required_skills":  ["Python", "Django"],
    }
    base.update(overrides)
    return base


class TestListJobs:
    def test_returns_200(self, client, db):
        assert client.get(f"{BASE}/").status_code == 200

    def test_success_envelope(self, client, db):
        body = client.get(f"{BASE}/").get_json()
        assert body["success"] is True

    def test_pagination_meta(self, client, db):
        meta = client.get(f"{BASE}/").get_json()["meta"]
        assert "total" in meta and "page" in meta

    def test_active_job_appears(self, client, db, sample_job):
        body = client.get(f"{BASE}/").get_json()
        ids = [j["id"] for j in body["data"]]
        assert sample_job.id in ids

    def test_closed_job_not_in_default_list(self, client, db, sample_job_closed):
        body = client.get(f"{BASE}/").get_json()
        ids = [j["id"] for j in body["data"]]
        assert sample_job_closed.id not in ids

    def test_search_filter(self, client, db, sample_job):
        body = client.get(f"{BASE}/?search=Senior Python").get_json()
        assert any(j["id"] == sample_job.id for j in body["data"])

    def test_location_filter(self, client, db, sample_job):
        body = client.get(f"{BASE}/?location=Remote").get_json()
        assert any(j["id"] == sample_job.id for j in body["data"])

    def test_job_type_filter(self, client, db, sample_job):
        body = client.get(f"{BASE}/?job_type=full-time").get_json()
        assert body["success"] is True

    def test_invalid_job_type_400(self, client, db):
        r = client.get(f"{BASE}/?job_type=gig-work")
        assert r.status_code == 400


class TestCreateJob:
    def test_returns_201(self, client, db, json_post):
        r, _ = json_post(f"{BASE}/", _job_payload())
        assert r.status_code == 201

    def test_id_in_response(self, client, db, json_post):
        _, body = json_post(f"{BASE}/", _job_payload())
        assert body["data"]["id"] is not None

    def test_fields_correct(self, client, db, json_post):
        payload = _job_payload()
        _, body = json_post(f"{BASE}/", payload)
        assert body["data"]["title"] == payload["title"]
        assert body["data"]["company"] == payload["company"]
        assert body["data"]["experience_years"] == payload["experience_years"]

    def test_required_skills_saved(self, client, db, json_post):
        _, body = json_post(f"{BASE}/", _job_payload())
        assert "Python" in body["data"]["required_skills"]

    def test_default_status_active(self, client, db, json_post):
        _, body = json_post(f"{BASE}/", _job_payload())
        assert body["data"]["status"] == "active"

    def test_missing_title_400(self, client, db, json_post):
        payload = _job_payload()
        del payload["title"]
        r, _ = json_post(f"{BASE}/", payload)
        assert r.status_code == 400

    def test_missing_company_400(self, client, db, json_post):
        payload = _job_payload()
        del payload["company"]
        r, _ = json_post(f"{BASE}/", payload)
        assert r.status_code == 400

    def test_description_too_short_400(self, client, db, json_post):
        r, _ = json_post(f"{BASE}/", _job_payload(description="Short"))
        assert r.status_code == 400

    def test_invalid_salary_range_400(self, client, db, json_post):
        r, body = json_post(f"{BASE}/", _job_payload(salary_min=100000, salary_max=50000))
        assert r.status_code == 400


class TestGetJob:
    def test_returns_200(self, client, db, sample_job):
        assert client.get(f"{BASE}/{sample_job.id}").status_code == 200

    def test_correct_data(self, client, db, sample_job):
        body = client.get(f"{BASE}/{sample_job.id}").get_json()
        assert body["data"]["id"] == sample_job.id
        assert body["data"]["title"] == sample_job.title

    def test_nonexistent_404(self, client, db):
        r = client.get(f"{BASE}/phantom-job")
        assert r.status_code == 404
        assert r.get_json()["error"]["error_code"] == "JOB_NOT_FOUND"


class TestUpdateJob:
    def test_returns_200(self, client, db, sample_job, json_patch):
        r, _ = json_patch(f"{BASE}/{sample_job.id}", {"location": "Bangalore, India"})
        assert r.status_code == 200

    def test_location_updated(self, client, db, sample_job, json_patch):
        _, body = json_patch(f"{BASE}/{sample_job.id}", {"location": "Hyderabad, India"})
        assert body["data"]["location"] == "Hyderabad, India"

    def test_partial_update_keeps_other_fields(self, client, db, sample_job, json_patch):
        original_title = sample_job.title
        _, body = json_patch(f"{BASE}/{sample_job.id}", {"location": "Chennai"})
        assert body["data"]["title"] == original_title

    def test_status_can_be_changed(self, client, db, sample_job, json_patch):
        _, body = json_patch(f"{BASE}/{sample_job.id}", {"status": "paused"})
        assert body["data"]["status"] == "paused"

    def test_invalid_status_400(self, client, db, sample_job, json_patch):
        r, _ = json_patch(f"{BASE}/{sample_job.id}", {"status": "invalid-status"})
        assert r.status_code == 400

    def test_nonexistent_404(self, client, db, json_patch):
        r, _ = json_patch(f"{BASE}/ghost-job", {"location": "X"})
        assert r.status_code == 404


class TestDeleteJob:
    def test_returns_204(self, client, db, sample_job):
        assert client.delete(f"{BASE}/{sample_job.id}").status_code == 204

    def test_deleted_is_404(self, client, db, sample_job):
        client.delete(f"{BASE}/{sample_job.id}")
        assert client.get(f"{BASE}/{sample_job.id}").status_code == 404

    def test_nonexistent_404(self, client, db):
        assert client.delete(f"{BASE}/phantom").status_code == 404


class TestJobCandidatesEndpoint:
    def test_returns_200(self, client, db, sample_job, mock_services):
        # Mock the ranking service
        from unittest.mock import MagicMock
        result = MagicMock()
        result.total      = 0
        result.page       = 1
        result.per_page   = 20
        result.candidates = []
        result.score_stats = MagicMock()
        result.score_stats.__dict__ = {"mean": 0.0}
        mock_services.candidate_ranking.rank_for_job.return_value = result

        r = client.get(f"{BASE}/{sample_job.id}/candidates")
        assert r.status_code == 200

    def test_nonexistent_job_404(self, client, db, mock_services):
        r = client.get(f"{BASE}/no-such-job/candidates")
        assert r.status_code == 404