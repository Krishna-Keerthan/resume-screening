
"""
tests/integration/test_recruiters.py

Integration tests for /api/v1/recruiters/* endpoints.
"""
import uuid
import pytest

BASE = "/api/v1/recruiters"


def _recruiter_payload(**overrides):
    base = {
        "full_name":    "Test Recruiter",
        "email":        f"recruiter+{uuid.uuid4().hex[:8]}@corp.com",
        "company_name": "Test Corp",
        "company_size": "51-200",
        "industry":     "Technology",
    }
    base.update(overrides)
    return base


class TestListRecruiters:
    def test_returns_200(self, client, db):
        assert client.get(f"{BASE}/").status_code == 200

    def test_success_envelope(self, client, db):
        body = client.get(f"{BASE}/").get_json()
        assert body["success"] is True

    def test_pagination_meta(self, client, db):
        meta = client.get(f"{BASE}/").get_json()["meta"]
        assert "total" in meta and "page" in meta and "limit" in meta

    def test_search_by_name(self, client, db, sample_recruiter):
        body = client.get(f"{BASE}/?search=HR Manager").get_json()
        found = [r for r in body["data"] if r["full_name"] == "HR Manager"]
        assert len(found) >= 1

    def test_search_by_company(self, client, db, sample_recruiter):
        body = client.get(f"{BASE}/?company_name=TechCorp").get_json()
        assert body["success"] is True


class TestCreateRecruiter:
    def test_returns_201(self, client, db, json_post):
        r, _ = json_post(f"{BASE}/", _recruiter_payload())
        assert r.status_code == 201

    def test_id_in_response(self, client, db, json_post):
        _, body = json_post(f"{BASE}/", _recruiter_payload())
        assert body["data"]["id"] is not None

    def test_fields_correct(self, client, db, json_post):
        payload = _recruiter_payload()
        _, body = json_post(f"{BASE}/", payload)
        assert body["data"]["company_name"] == payload["company_name"]
        assert body["data"]["industry"] == payload["industry"]

    def test_missing_email_400(self, client, db, json_post):
        payload = _recruiter_payload()
        del payload["email"]
        r, _ = json_post(f"{BASE}/", payload)
        assert r.status_code == 400

    def test_missing_full_name_400(self, client, db, json_post):
        payload = _recruiter_payload()
        del payload["full_name"]
        r, _ = json_post(f"{BASE}/", payload)
        assert r.status_code == 400

    def test_duplicate_email_409(self, client, db, json_post, sample_recruiter):
        r, body = json_post(f"{BASE}/", _recruiter_payload(email=sample_recruiter.email))
        assert r.status_code == 409
        assert body["error"]["error_code"] == "RECRUITER_EMAIL_CONFLICT"

    def test_invalid_company_size_400(self, client, db, json_post):
        r, _ = json_post(f"{BASE}/", _recruiter_payload(company_size="gigantic"))
        assert r.status_code == 400


class TestGetRecruiter:
    def test_returns_200(self, client, db, sample_recruiter):
        r = client.get(f"{BASE}/{sample_recruiter.id}")
        assert r.status_code == 200

    def test_correct_id(self, client, db, sample_recruiter):
        body = client.get(f"{BASE}/{sample_recruiter.id}").get_json()
        assert body["data"]["id"] == sample_recruiter.id

    def test_correct_company(self, client, db, sample_recruiter):
        body = client.get(f"{BASE}/{sample_recruiter.id}").get_json()
        assert body["data"]["company_name"] == sample_recruiter.company_name

    def test_nonexistent_404(self, client, db):
        r = client.get(f"{BASE}/no-such-recruiter")
        assert r.status_code == 404
        assert r.get_json()["error"]["error_code"] == "RECRUITER_NOT_FOUND"


class TestUpdateRecruiter:
    def test_returns_200(self, client, db, sample_recruiter, json_patch):
        r, _ = json_patch(f"{BASE}/{sample_recruiter.id}", {"industry": "Fintech"})
        assert r.status_code == 200

    def test_industry_updated(self, client, db, sample_recruiter, json_patch):
        _, body = json_patch(f"{BASE}/{sample_recruiter.id}", {"industry": "Fintech"})
        assert body["data"]["industry"] == "Fintech"

    def test_partial_update(self, client, db, sample_recruiter, json_patch):
        original_name = sample_recruiter.full_name
        _, body = json_patch(f"{BASE}/{sample_recruiter.id}", {"industry": "Healthcare"})
        assert body["data"]["full_name"] == original_name

    def test_nonexistent_404(self, client, db, json_patch):
        r, _ = json_patch(f"{BASE}/ghost", {"industry": "x"})
        assert r.status_code == 404


class TestDeleteRecruiter:
    def test_returns_204(self, client, db, sample_recruiter):
        assert client.delete(f"{BASE}/{sample_recruiter.id}").status_code == 204

    def test_deleted_is_404(self, client, db, sample_recruiter):
        client.delete(f"{BASE}/{sample_recruiter.id}")
        assert client.get(f"{BASE}/{sample_recruiter.id}").status_code == 404

    def test_nonexistent_404(self, client, db):
        assert client.delete(f"{BASE}/ghost-rec").status_code == 404


class TestRecruiterJobs:
    def test_returns_200(self, client, db, sample_recruiter, sample_job):
        r = client.get(f"{BASE}/{sample_recruiter.id}/jobs")
        assert r.status_code == 200

    def test_returns_job(self, client, db, sample_recruiter, sample_job):
        body = client.get(f"{BASE}/{sample_recruiter.id}/jobs").get_json()
        ids = [j["id"] for j in body["data"]]
        assert sample_job.id in ids

    def test_filter_by_status(self, client, db, sample_recruiter, sample_job):
        body = client.get(f"{BASE}/{sample_recruiter.id}/jobs?status=active").get_json()
        assert all(j["status"] == "active" for j in body["data"])

    def test_nonexistent_recruiter_404(self, client, db):
        assert client.get(f"{BASE}/ghost/jobs").status_code == 404