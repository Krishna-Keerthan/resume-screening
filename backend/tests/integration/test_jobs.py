"""
tests/integration/test_jobs.py

Integration tests for /api/v1/jobs/* endpoints.
"""
import uuid
from types import SimpleNamespace

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


@pytest.fixture()
def draft_job_a(db, job_a):
    job_a.status = "draft"
    db.session.commit()
    return job_a


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

    def test_recruiter_can_filter_their_own_jobs_by_status(
        self, client, db, sample_job, sample_job_closed, sample_recruiter, headers_for
    ):
        r = client.get(f"{BASE}/?status=closed", headers=headers_for(sample_recruiter))
        assert r.status_code == 200
        assert [j["id"] for j in r.get_json()["data"]] == [sample_job_closed.id]

    def test_recruiter_never_sees_other_recruiters_non_active_jobs(
        self, client, db, sample_job_closed, recruiter_a, headers_for
    ):
        r = client.get(f"{BASE}/?status=closed", headers=headers_for(recruiter_a))
        assert r.get_json()["data"] == []

    def test_recruiter_can_list_their_drafts(self, client, db, draft_job_a, recruiter_a, headers_for):
        r = client.get(f"{BASE}/?status=draft", headers=headers_for(recruiter_a))
        assert [j["id"] for j in r.get_json()["data"]] == [draft_job_a.id]

    def test_anonymous_status_filter_still_lists_only_active_jobs(
        self, client, db, sample_job, sample_job_closed, draft_job_a, anon
    ):
        for status in ("closed", "draft", "paused"):
            ids = [j["id"] for j in client.get(f"{BASE}/?status={status}", headers=anon).get_json()["data"]]
            assert sample_job.id in ids
            assert sample_job_closed.id not in ids
            assert draft_job_a.id not in ids

    def test_candidate_status_filter_still_lists_only_active_jobs(
        self, client, db, sample_job, sample_job_closed, candidate_a, headers_for
    ):
        body = client.get(f"{BASE}/?status=closed", headers=headers_for(candidate_a)).get_json()
        ids = [j["id"] for j in body["data"]]
        assert sample_job.id in ids and sample_job_closed.id not in ids

    def test_invalid_job_type_400(self, client, db):
        r = client.get(f"{BASE}/?job_type=gig-work")
        assert r.status_code == 400

    def test_recruiter_id_query_param_is_ignored(self, client, db, job_a, job_b, recruiter_a):
        body = client.get(f"{BASE}/?recruiter_id={recruiter_a.id}").get_json()
        ids = {j["id"] for j in body["data"]}
        assert {job_a.id, job_b.id} <= ids


class TestCreateJob:
    @pytest.fixture(autouse=True)
    def _auth(self, recruiter_a, headers_for):
        self.recruiter = recruiter_a
        self.headers = headers_for(recruiter_a)

    def test_returns_201(self, client, db, json_post):
        r, _ = json_post(f"{BASE}/", _job_payload(), headers=self.headers)
        assert r.status_code == 201

    def test_id_in_response(self, client, db, json_post):
        _, body = json_post(f"{BASE}/", _job_payload(), headers=self.headers)
        assert body["data"]["id"] is not None

    def test_fields_correct(self, client, db, json_post):
        payload = _job_payload()
        _, body = json_post(f"{BASE}/", payload, headers=self.headers)
        assert body["data"]["title"] == payload["title"]
        assert body["data"]["company"] == payload["company"]
        assert body["data"]["experience_years"] == payload["experience_years"]

    def test_required_skills_saved(self, client, db, json_post):
        _, body = json_post(f"{BASE}/", _job_payload(), headers=self.headers)
        assert "Python" in body["data"]["required_skills"]

    def test_default_status_active(self, client, db, json_post):
        _, body = json_post(f"{BASE}/", _job_payload(), headers=self.headers)
        assert body["data"]["status"] == "active"

    def test_missing_title_400(self, client, db, json_post):
        payload = _job_payload()
        del payload["title"]
        r, _ = json_post(f"{BASE}/", payload, headers=self.headers)
        assert r.status_code == 400

    def test_missing_company_400(self, client, db, json_post):
        payload = _job_payload()
        del payload["company"]
        r, _ = json_post(f"{BASE}/", payload, headers=self.headers)
        assert r.status_code == 400

    def test_description_too_short_400(self, client, db, json_post):
        r, _ = json_post(f"{BASE}/", _job_payload(description="Short"), headers=self.headers)
        assert r.status_code == 400

    def test_invalid_salary_range_400(self, client, db, json_post):
        r, body = json_post(f"{BASE}/", _job_payload(salary_min=100000, salary_max=50000),
                            headers=self.headers)
        assert r.status_code == 400

    def test_no_token_401(self, client, db, json_post, anon):
        r, _ = json_post(f"{BASE}/", _job_payload(), headers=anon)
        assert r.status_code == 401

    def test_candidate_token_403(self, client, db, json_post, candidate_a, headers_for):
        r, _ = json_post(f"{BASE}/", _job_payload(), headers=headers_for(candidate_a))
        assert r.status_code == 403

    def test_recruiter_id_comes_from_the_token_not_the_body(
        self, client, db, json_post, recruiter_b
    ):
        r, body = json_post(f"{BASE}/", _job_payload(recruiter_id=recruiter_b.id),
                            headers=self.headers)
        assert r.status_code == 201
        assert body["data"]["recruiter_id"] == self.recruiter.id


class TestGetJob:
    def test_active_job_is_public(self, client, db, sample_job, anon):
        r = client.get(f"{BASE}/{sample_job.id}", headers=anon)
        assert r.status_code == 200
        assert r.get_json()["data"]["id"] == sample_job.id
        assert r.get_json()["data"]["title"] == sample_job.title

    def test_nonexistent_404(self, client, db):
        r = client.get(f"{BASE}/phantom-job")
        assert r.status_code == 404
        assert r.get_json()["error"]["error_code"] == "JOB_NOT_FOUND"

    @pytest.mark.parametrize("fixture_name", ["draft_job_a", "sample_job_closed"])
    def test_non_active_job_is_404_to_anonymous_candidates_and_other_recruiters(
        self, request, client, db, fixture_name, candidate_a, recruiter_b, headers_for, anon
    ):
        job = request.getfixturevalue(fixture_name)
        for headers in (anon, headers_for(candidate_a), headers_for(recruiter_b)):
            r = client.get(f"{BASE}/{job.id}", headers=headers)
            assert r.status_code == 404
            assert r.get_json()["error"]["error_code"] == "JOB_NOT_FOUND"

    def test_non_active_job_is_visible_to_its_recruiter(self, client, db, draft_job_a, recruiter_a, headers_for):
        r = client.get(f"{BASE}/{draft_job_a.id}", headers=headers_for(recruiter_a))
        assert r.status_code == 200
        assert r.get_json()["data"]["id"] == draft_job_a.id

    def test_closed_job_is_visible_to_its_recruiter(
        self, client, db, sample_job_closed, sample_recruiter, headers_for
    ):
        assert client.get(f"{BASE}/{sample_job_closed.id}", headers=headers_for(sample_recruiter)).status_code == 200


class TestUpdateJob:
    def test_access_rules(self, check_access, job_a, recruiter_a, recruiter_b):
        r = check_access("PATCH", f"{BASE}/{job_a.id}", owner=recruiter_a, other=recruiter_b,
                         json={"location": "Hyderabad, India"})
        assert r.get_json()["data"]["location"] == "Hyderabad, India"

    def test_non_owner_cannot_change_anything(self, client, db, job_a, recruiter_b, headers_for):
        client.patch(f"{BASE}/{job_a.id}", json={"title": "Hijacked"}, headers=headers_for(recruiter_b))
        db.session.refresh(job_a)
        assert job_a.title == "Job A"

    def test_non_owner_gets_404_for_a_job_that_is_not_active(
        self, check_access, draft_job_a, recruiter_a, recruiter_b
    ):
        check_access("PATCH", f"{BASE}/{draft_job_a.id}", owner=recruiter_a, other=recruiter_b,
                     json={"location": "X"}, other_status=404)

    def test_candidate_token_403(self, client, db, job_a, candidate_a, headers_for):
        r = client.patch(f"{BASE}/{job_a.id}", json={"location": "X"}, headers=headers_for(candidate_a))
        assert r.status_code == 403

    def test_partial_update_keeps_other_fields(self, client, db, job_a, recruiter_a, headers_for):
        r = client.patch(f"{BASE}/{job_a.id}", json={"location": "Chennai"}, headers=headers_for(recruiter_a))
        assert r.get_json()["data"]["title"] == "Job A"

    def test_status_can_be_changed(self, client, db, job_a, recruiter_a, headers_for):
        r = client.patch(f"{BASE}/{job_a.id}", json={"status": "paused"}, headers=headers_for(recruiter_a))
        assert r.get_json()["data"]["status"] == "paused"

    def test_invalid_status_400(self, client, db, job_a, recruiter_a, headers_for):
        r = client.patch(f"{BASE}/{job_a.id}", json={"status": "invalid-status"}, headers=headers_for(recruiter_a))
        assert r.status_code == 400

    def test_recruiter_id_in_the_body_is_ignored(self, client, db, job_a, recruiter_a, recruiter_b, headers_for):
        r = client.patch(f"{BASE}/{job_a.id}", json={"recruiter_id": recruiter_b.id, "location": "X"},
                         headers=headers_for(recruiter_a))
        assert r.status_code == 200
        db.session.refresh(job_a)
        assert job_a.recruiter_id == recruiter_a.id

    def test_nonexistent_404(self, client, db, recruiter_a, headers_for):
        r = client.patch(f"{BASE}/ghost-job", json={"location": "X"}, headers=headers_for(recruiter_a))
        assert r.status_code == 404


class TestDeleteJob:
    def test_access_rules(self, check_access, job_a, recruiter_a, recruiter_b):
        r = check_access("DELETE", f"{BASE}/{job_a.id}", owner=recruiter_a, other=recruiter_b)
        assert r.status_code == 204

    def test_non_owner_cannot_delete(self, client, db, job_a, recruiter_b, headers_for):
        client.delete(f"{BASE}/{job_a.id}", headers=headers_for(recruiter_b))
        db.session.refresh(job_a)
        assert job_a.is_deleted is False

    def test_non_owner_gets_404_for_a_job_that_is_not_active(
        self, check_access, draft_job_a, recruiter_a, recruiter_b
    ):
        check_access("DELETE", f"{BASE}/{draft_job_a.id}", owner=recruiter_a, other=recruiter_b,
                     other_status=404)

    def test_deleted_is_404(self, client, db, job_a, recruiter_a, headers_for):
        client.delete(f"{BASE}/{job_a.id}", headers=headers_for(recruiter_a))
        assert client.get(f"{BASE}/{job_a.id}").status_code == 404

    def test_nonexistent_404(self, client, db, recruiter_a, headers_for):
        assert client.delete(f"{BASE}/phantom", headers=headers_for(recruiter_a)).status_code == 404


def _ranking(**overrides):
    fields = dict(total=0, page=1, per_page=20, candidates=[])
    fields.update(overrides)
    return SimpleNamespace(**fields)


class TestJobCandidatesEndpoint:
    def test_access_rules(self, check_access, job_a, recruiter_a, recruiter_b, mock_services):
        mock_services.candidate_ranking.rank_for_job.return_value = _ranking()
        check_access("GET", f"{BASE}/{job_a.id}/candidates", owner=recruiter_a, other=recruiter_b)

    def test_non_owner_gets_404_for_a_job_that_is_not_active(
        self, check_access, draft_job_a, recruiter_a, recruiter_b, mock_services
    ):
        mock_services.candidate_ranking.rank_for_job.return_value = _ranking()
        check_access("GET", f"{BASE}/{draft_job_a.id}/candidates", owner=recruiter_a,
                     other=recruiter_b, other_status=404)

    def test_nonexistent_job_404(self, client, db, recruiter_a, headers_for, mock_services):
        r = client.get(f"{BASE}/no-such-job/candidates", headers=headers_for(recruiter_a))
        assert r.status_code == 404


class TestJobSkillGapsEndpoint:
    def test_access_rules(self, check_access, job_a, recruiter_a, recruiter_b, mock_services):
        mock_services.candidate_ranking.get_skill_gap_summary.return_value = {"most_common_missing": []}
        check_access("GET", f"{BASE}/{job_a.id}/skill-gaps", owner=recruiter_a, other=recruiter_b)

    def test_non_owner_gets_404_for_a_job_that_is_not_active(
        self, check_access, draft_job_a, recruiter_a, recruiter_b, mock_services
    ):
        mock_services.candidate_ranking.get_skill_gap_summary.return_value = {}
        check_access("GET", f"{BASE}/{draft_job_a.id}/skill-gaps", owner=recruiter_a,
                     other=recruiter_b, other_status=404)


class TestEnhanceJobEndpoint:
    @staticmethod
    def _enhancement(job):
        return SimpleNamespace(
            job_id=job.id, required_skills=[], nice_to_have_skills=[], responsibilities=[],
            enhanced_description="", quality_score=0.5, completeness_score=0.5,
            suggestions=[], duplicate_ids=[], llm_enhanced=False,
        )

    def test_access_rules(self, check_access, job_a, recruiter_a, recruiter_b, mock_services):
        mock_services.smart_job_posting.enhance.return_value = self._enhancement(job_a)
        check_access("POST", f"{BASE}/{job_a.id}/enhance", owner=recruiter_a, other=recruiter_b,
                     json={"use_llm": False})

    def test_non_owner_cannot_trigger_enhancement(
        self, client, db, job_a, recruiter_b, headers_for, mock_services
    ):
        client.post(f"{BASE}/{job_a.id}/enhance", json={}, headers=headers_for(recruiter_b))
        mock_services.smart_job_posting.enhance.assert_not_called()

    def test_non_owner_gets_404_for_a_job_that_is_not_active(
        self, check_access, draft_job_a, recruiter_a, recruiter_b, mock_services
    ):
        mock_services.smart_job_posting.enhance.return_value = self._enhancement(draft_job_a)
        check_access("POST", f"{BASE}/{draft_job_a.id}/enhance", owner=recruiter_a,
                     other=recruiter_b, json={}, other_status=404)


class TestJobPerformanceEndpoint:
    def test_access_rules(self, check_access, job_a, recruiter_a, recruiter_b, mock_services):
        mock_services.recruiter_analytics.get_job_performance.return_value = {"job_id": job_a.id}
        r = check_access("GET", f"{BASE}/{job_a.id}/performance", owner=recruiter_a, other=recruiter_b)
        assert r.get_json()["data"]["job_id"] == job_a.id

    def test_non_owner_gets_404_for_a_job_that_is_not_active(
        self, check_access, draft_job_a, recruiter_a, recruiter_b, mock_services
    ):
        mock_services.recruiter_analytics.get_job_performance.return_value = {"job_id": draft_job_a.id}
        check_access("GET", f"{BASE}/{draft_job_a.id}/performance", owner=recruiter_a,
                     other=recruiter_b, other_status=404)

    def test_ownership_is_decided_by_the_route_not_the_service(
        self, client, db, job_a, recruiter_a, headers_for, mock_services
    ):
        mock_services.recruiter_analytics.get_job_performance.return_value = {"job_id": job_a.id}
        client.get(f"{BASE}/{job_a.id}/performance", headers=headers_for(recruiter_a))
        mock_services.recruiter_analytics.get_job_performance.assert_called_once_with(job_id=job_a.id)

    def test_nonexistent_404(self, client, db, recruiter_a, headers_for, mock_services):
        assert client.get(f"{BASE}/phantom/performance", headers=headers_for(recruiter_a)).status_code == 404
