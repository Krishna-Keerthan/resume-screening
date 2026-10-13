"""
tests/integration/test_applications.py

Integration tests for /api/v1/applications/* endpoints.
Tests business rules: duplicate guard, inactive job guard, ownership guard,
stage transitions, and who may see or change an application.
"""
import uuid
from types import SimpleNamespace

import pytest

BASE = "/api/v1/applications"


@pytest.fixture()
def draft_job_a(db, job_a):
    job_a.status = "draft"
    db.session.commit()
    return job_a


class TestListApplications:
    def test_no_token_401(self, client, db, anon):
        assert client.get(f"{BASE}/", headers=anon).status_code == 401

    def test_candidate_sees_own_applications(
        self, client, db, application_a, candidate_a, headers_for
    ):
        r = client.get(f"{BASE}/", headers=headers_for(candidate_a))
        assert r.status_code == 200
        assert r.get_json()["success"] is True
        assert [a["id"] for a in r.get_json()["data"]] == [application_a.id]

    def test_candidate_does_not_see_other_candidates_applications(
        self, client, db, application_a, candidate_b, headers_for
    ):
        body = client.get(f"{BASE}/", headers=headers_for(candidate_b)).get_json()
        assert body["data"] == []

    def test_candidate_id_query_param_is_ignored(
        self, client, db, application_a, candidate_a, candidate_b, headers_for
    ):
        r = client.get(f"{BASE}/?candidate_id={candidate_a.id}", headers=headers_for(candidate_b))
        assert r.get_json()["data"] == []

    def test_candidate_job_id_param_cannot_widen_the_list(
        self, client, db, application_a, job_a, candidate_b, headers_for
    ):
        r = client.get(f"{BASE}/?job_id={job_a.id}", headers=headers_for(candidate_b))
        assert r.status_code == 200
        assert r.get_json()["data"] == []

    def test_candidate_filter_by_stage(self, client, db, application_a, candidate_a, headers_for):
        applied = client.get(f"{BASE}/?stage=applied", headers=headers_for(candidate_a)).get_json()
        hired = client.get(f"{BASE}/?stage=hired", headers=headers_for(candidate_a)).get_json()
        assert [a["id"] for a in applied["data"]] == [application_a.id]
        assert hired["data"] == []

    def test_recruiter_lists_applications_for_their_job(
        self, check_access, application_a, job_a, recruiter_a, recruiter_b
    ):
        r = check_access("GET", f"{BASE}/?job_id={job_a.id}", owner=recruiter_a, other=recruiter_b)
        assert [a["id"] for a in r.get_json()["data"]] == [application_a.id]

    def test_recruiter_must_name_a_job(self, client, db, application_a, recruiter_a, headers_for):
        r = client.get(f"{BASE}/", headers=headers_for(recruiter_a))
        assert r.status_code == 400

    def test_recruiter_cannot_list_another_recruiters_job(
        self, client, db, application_a, job_b, recruiter_a, headers_for
    ):
        r = client.get(f"{BASE}/?job_id={job_b.id}", headers=headers_for(recruiter_a))
        assert r.status_code == 403


class TestCreateApplication:
    @pytest.fixture(autouse=True)
    def _auth(self, candidate_a, headers_for, mock_services):
        self.candidate = candidate_a
        self.headers = headers_for(candidate_a)
        scored = mock_services.ats_scorer.score_resume_job.return_value
        scored.error = None
        scored.final_score = 0.75
        scored.score_label = "good"

    @staticmethod
    def _payload(job_id, resume_id, **extra):
        return {"job_id": job_id, "resume_id": resume_id, **extra}

    def test_returns_201(self, client, db, json_post, job_a, resume_a):
        r, body = json_post(f"{BASE}/", self._payload(job_a.id, resume_a.id), headers=self.headers)
        assert r.status_code == 201
        assert body["data"]["stage"] == "applied"

    def test_candidate_comes_from_the_token_not_the_body(
        self, client, db, json_post, job_a, resume_a, candidate_b
    ):
        r, body = json_post(
            f"{BASE}/",
            self._payload(job_a.id, resume_a.id, candidate_id=candidate_b.id),
            headers=self.headers,
        )
        assert r.status_code == 201
        assert body["data"]["candidate_id"] == self.candidate.id

    def test_no_token_401(self, client, db, json_post, job_a, resume_a, anon):
        r, _ = json_post(f"{BASE}/", self._payload(job_a.id, resume_a.id), headers=anon)
        assert r.status_code == 401

    def test_recruiter_token_403(self, client, db, json_post, job_a, resume_a, recruiter_a, headers_for):
        r, _ = json_post(f"{BASE}/", self._payload(job_a.id, resume_a.id), headers=headers_for(recruiter_a))
        assert r.status_code == 403

    def test_duplicate_application_409(self, client, db, json_post, application_a):
        r, body = json_post(
            f"{BASE}/",
            self._payload(application_a.job_id, application_a.resume_id),
            headers=self.headers,
        )
        assert r.status_code == 409
        assert body["error"]["error_code"] == "DUPLICATE_APPLICATION"

    def test_inactive_job_422(self, client, db, json_post, draft_job_a, resume_a):
        r, body = json_post(f"{BASE}/", self._payload(draft_job_a.id, resume_a.id), headers=self.headers)
        assert r.status_code == 422
        assert body["error"]["error_code"] == "JOB_NOT_ACTIVE"

    def test_nonexistent_job_404(self, client, db, json_post, resume_a):
        r, _ = json_post(f"{BASE}/", self._payload(str(uuid.uuid4()), resume_a.id), headers=self.headers)
        assert r.status_code == 404

    def test_nonexistent_resume_404(self, client, db, json_post, job_a):
        r, _ = json_post(f"{BASE}/", self._payload(job_a.id, str(uuid.uuid4())), headers=self.headers)
        assert r.status_code == 404

    def test_someone_elses_resume_403(self, client, db, json_post, job_a, resume_b):
        r, body = json_post(f"{BASE}/", self._payload(job_a.id, resume_b.id), headers=self.headers)
        assert r.status_code == 403
        assert body["error"]["error_code"] == "RESUME_OWNERSHIP_MISMATCH"

    def test_missing_fields_400(self, client, db, json_post):
        r, _ = json_post(f"{BASE}/", {"job_id": "x"}, headers=self.headers)
        assert r.status_code == 400


class TestGetApplication:
    def test_access_rules_for_the_candidate(
        self, check_access, application_a, candidate_a, candidate_b
    ):
        r = check_access("GET", f"{BASE}/{application_a.id}", owner=candidate_a, other=candidate_b)
        assert r.get_json()["data"]["id"] == application_a.id
        assert r.get_json()["data"]["stage"] == "applied"

    def test_access_rules_for_the_jobs_recruiter(
        self, check_access, application_a, recruiter_a, recruiter_b
    ):
        check_access("GET", f"{BASE}/{application_a.id}", owner=recruiter_a, other=recruiter_b)

    def test_nonexistent_404(self, client, db, candidate_a, headers_for):
        assert client.get(f"{BASE}/phantom-app", headers=headers_for(candidate_a)).status_code == 404


class TestUpdateApplicationStage:
    def test_access_rules(self, check_access, application_a, recruiter_a, recruiter_b):
        r = check_access("PATCH", f"{BASE}/{application_a.id}/stage",
                         owner=recruiter_a, other=recruiter_b, json={"stage": "reviewed"})
        assert r.get_json()["data"]["stage"] == "reviewed"

    def test_non_owner_cannot_change_the_stage(
        self, client, db, application_a, recruiter_b, headers_for
    ):
        client.patch(f"{BASE}/{application_a.id}/stage", json={"stage": "reviewed"},
                     headers=headers_for(recruiter_b))
        db.session.refresh(application_a)
        assert application_a.stage == "applied"

    def test_the_applicant_cannot_advance_their_own_application(
        self, client, db, application_a, candidate_a, headers_for
    ):
        r = client.patch(f"{BASE}/{application_a.id}/stage", json={"stage": "hired"},
                         headers=headers_for(candidate_a))
        assert r.status_code == 403

    def test_the_actor_is_the_authenticated_recruiter(
        self, client, db, application_a, recruiter_a, recruiter_b, headers_for
    ):
        client.patch(f"{BASE}/{application_a.id}/stage",
                     json={"stage": "reviewed", "actor_id": recruiter_b.id},
                     headers=headers_for(recruiter_a))
        db.session.refresh(application_a)
        assert application_a.stage_history_list[-1]["by"] == recruiter_a.id

    def test_recruiter_notes_saved(self, client, db, application_a, recruiter_a, headers_for):
        r = client.patch(f"{BASE}/{application_a.id}/stage",
                         json={"stage": "reviewed", "recruiter_notes": "Strong candidate, move forward."},
                         headers=headers_for(recruiter_a))
        assert r.get_json()["data"]["recruiter_notes"] == "Strong candidate, move forward."

    def test_rejection_reason_saved(self, client, db, application_a, recruiter_a, headers_for):
        r = client.patch(f"{BASE}/{application_a.id}/stage",
                         json={"stage": "rejected", "rejection_reason": "Overqualified."},
                         headers=headers_for(recruiter_a))
        assert r.get_json()["data"]["rejection_reason"] == "Overqualified."

    def test_invalid_stage_400(self, client, db, application_a, recruiter_a, headers_for):
        r = client.patch(f"{BASE}/{application_a.id}/stage", json={"stage": "flying"},
                         headers=headers_for(recruiter_a))
        assert r.status_code == 400

    def test_nonexistent_404(self, client, db, recruiter_a, headers_for):
        r = client.patch(f"{BASE}/ghost/stage", json={"stage": "reviewed"}, headers=headers_for(recruiter_a))
        assert r.status_code == 404


class TestWithdrawApplication:
    def test_access_rules(self, check_access, application_a, candidate_a, candidate_b):
        r = check_access("DELETE", f"{BASE}/{application_a.id}", owner=candidate_a, other=candidate_b)
        assert r.status_code == 204

    def test_the_jobs_recruiter_cannot_withdraw_it(
        self, client, db, application_a, recruiter_a, headers_for
    ):
        r = client.delete(f"{BASE}/{application_a.id}", headers=headers_for(recruiter_a))
        assert r.status_code == 403

    def test_non_owner_cannot_withdraw(self, client, db, application_a, candidate_b, headers_for):
        client.delete(f"{BASE}/{application_a.id}", headers=headers_for(candidate_b))
        db.session.refresh(application_a)
        assert application_a.stage == "applied"

    def test_after_withdraw_stage_is_withdrawn(
        self, client, db, application_a, candidate_a, recruiter_a, headers_for
    ):
        client.patch(f"{BASE}/{application_a.id}/stage", json={"stage": "reviewed"},
                     headers=headers_for(recruiter_a))
        client.delete(f"{BASE}/{application_a.id}", headers=headers_for(candidate_a))
        body = client.get(f"{BASE}/{application_a.id}", headers=headers_for(candidate_a)).get_json()
        assert body["data"]["stage"] == "withdrawn"

    def test_cannot_withdraw_hired(
        self, client, db, application_a, candidate_a, recruiter_a, headers_for
    ):
        for stage in ["reviewed", "shortlisted", "interviewing", "offered", "hired"]:
            client.patch(f"{BASE}/{application_a.id}/stage", json={"stage": stage},
                         headers=headers_for(recruiter_a))

        r = client.delete(f"{BASE}/{application_a.id}", headers=headers_for(candidate_a))
        assert r.status_code == 422
        assert r.get_json()["error"]["error_code"] == "CANNOT_WITHDRAW"

    def test_nonexistent_404(self, client, db, candidate_a, headers_for):
        assert client.delete(f"{BASE}/no-such-app", headers=headers_for(candidate_a)).status_code == 404


class TestScoreApplication:
    @staticmethod
    def _score_result(application):
        return SimpleNamespace(
            error=None, resume_id=application.resume_id, job_id=application.job_id,
            final_score=0.8, score_label="good", semantic_score=0.8, keyword_score=0.8,
            experience_score=0.8, section_quality_score=0.8, matched_skills=[],
            missing_skills=[], improvement_tips=[], summary_text="", hiring_recommendation="",
            ats_score_id="s1",
        )

    def test_access_rules(self, check_access, application_a, recruiter_a, recruiter_b, mock_services):
        mock_services.ats_scorer.score_resume_job.return_value = self._score_result(application_a)
        check_access("POST", f"{BASE}/{application_a.id}/score",
                     owner=recruiter_a, other=recruiter_b, json={"use_llm": False})

    def test_non_owner_cannot_trigger_scoring(
        self, client, db, application_a, recruiter_b, headers_for, mock_services
    ):
        client.post(f"{BASE}/{application_a.id}/score", json={}, headers=headers_for(recruiter_b))
        mock_services.ats_scorer.score_resume_job.assert_not_called()

    def test_the_applicant_gets_403(self, client, db, application_a, candidate_a, headers_for, mock_services):
        r = client.post(f"{BASE}/{application_a.id}/score", json={}, headers=headers_for(candidate_a))
        assert r.status_code == 403


class TestAiSummary:
    def test_access_rules(self, check_access, application_a, recruiter_a, recruiter_b, mock_services):
        mock_services.groq.available = True
        mock_services.groq.generate_candidate_summary.return_value = {
            "summary": "ok", "recommendation": "maybe",
        }
        check_access("GET", f"{BASE}/{application_a.id}/ai-summary",
                     owner=recruiter_a, other=recruiter_b)

    def test_non_owner_cannot_generate_a_summary(
        self, client, db, application_a, recruiter_b, headers_for, mock_services
    ):
        mock_services.groq.available = True
        client.get(f"{BASE}/{application_a.id}/ai-summary", headers=headers_for(recruiter_b))
        mock_services.groq.generate_candidate_summary.assert_not_called()
