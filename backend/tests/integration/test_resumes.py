"""
tests/integration/test_resumes.py

Integration tests for /api/v1/resumes/* endpoints.

A resume belongs to its candidate. A recruiter may read one only when it is
attached to an application to one of their jobs; everything else is
candidate-only.
"""
from types import SimpleNamespace

import pytest

BASE = "/api/v1/resumes"


@pytest.fixture()
def draft_job_a(db, job_a):
    job_a.status = "draft"
    db.session.commit()
    return job_a


class TestListResumes:
    def test_no_token_401(self, client, db, anon):
        assert client.get(f"{BASE}/", headers=anon).status_code == 401

    def test_recruiter_403(self, client, db, recruiter_a, headers_for):
        assert client.get(f"{BASE}/", headers=headers_for(recruiter_a)).status_code == 403

    def test_candidate_sees_only_their_own_resumes(
        self, client, db, resume_a, resume_b, candidate_a, headers_for
    ):
        r = client.get(f"{BASE}/", headers=headers_for(candidate_a))
        assert r.status_code == 200
        assert r.get_json()["success"] is True
        assert [x["id"] for x in r.get_json()["data"]] == [resume_a.id]
        assert r.get_json()["meta"]["total"] == 1

    def test_candidate_id_query_param_is_ignored(
        self, client, db, resume_a, resume_b, candidate_a, headers_for
    ):
        r = client.get(f"{BASE}/?candidate_id={resume_b.candidate_id}", headers=headers_for(candidate_a))
        assert [x["id"] for x in r.get_json()["data"]] == [resume_a.id]

    def test_filter_by_parse_status(self, client, db, resume_a, candidate_a, headers_for):
        hit = client.get(f"{BASE}/?parse_status=success", headers=headers_for(candidate_a)).get_json()
        miss = client.get(f"{BASE}/?parse_status=failed", headers=headers_for(candidate_a)).get_json()
        assert [x["id"] for x in hit["data"]] == [resume_a.id]
        assert miss["data"] == []

    def test_invalid_parse_status_400(self, client, db, candidate_a, headers_for):
        r = client.get(f"{BASE}/?parse_status=unknown_status", headers=headers_for(candidate_a))
        assert r.status_code == 400


class TestGetResume:
    def test_access_rules_for_the_candidate(self, check_access, resume_a, candidate_a, candidate_b):
        r = check_access("GET", f"{BASE}/{resume_a.id}", owner=candidate_a, other=candidate_b)
        data = r.get_json()["data"]
        assert data["id"] == resume_a.id
        assert data["candidate_id"] == candidate_a.id
        assert data["parse_status"] == "success"
        assert "Python" in data["skills"]
        assert data["total_experience_years"] == resume_a.total_experience_years

    def test_access_rules_for_a_recruiter_with_an_application(
        self, check_access, application_a, resume_a, recruiter_a, recruiter_b
    ):
        check_access("GET", f"{BASE}/{resume_a.id}", owner=recruiter_a, other=recruiter_b)

    def test_recruiter_cannot_read_a_resume_that_was_not_submitted_to_them(
        self, client, db, application_a, resume_b, recruiter_a, headers_for
    ):
        assert client.get(f"{BASE}/{resume_b.id}", headers=headers_for(recruiter_a)).status_code == 403

    def test_nonexistent_404(self, client, db, candidate_a, headers_for):
        r = client.get(f"{BASE}/no-such-resume", headers=headers_for(candidate_a))
        assert r.status_code == 404
        assert r.get_json()["error"]["error_code"] == "RESUME_NOT_FOUND"


class TestDeleteResume:
    def test_access_rules(self, check_access, resume_a, candidate_a, candidate_b):
        r = check_access("DELETE", f"{BASE}/{resume_a.id}", owner=candidate_a, other=candidate_b)
        assert r.status_code == 204

    def test_another_candidate_cannot_delete(self, client, db, resume_a, candidate_b, headers_for):
        client.delete(f"{BASE}/{resume_a.id}", headers=headers_for(candidate_b))
        db.session.refresh(resume_a)
        assert resume_a.is_deleted is False

    def test_a_recruiter_cannot_delete_even_with_an_application(
        self, client, db, application_a, resume_a, recruiter_a, headers_for
    ):
        assert client.delete(f"{BASE}/{resume_a.id}", headers=headers_for(recruiter_a)).status_code == 403

    def test_deleted_is_404(self, client, db, resume_a, candidate_a, headers_for):
        client.delete(f"{BASE}/{resume_a.id}", headers=headers_for(candidate_a))
        assert client.get(f"{BASE}/{resume_a.id}", headers=headers_for(candidate_a)).status_code == 404

    def test_nonexistent_404(self, client, db, candidate_a, headers_for):
        assert client.delete(f"{BASE}/phantom-resume", headers=headers_for(candidate_a)).status_code == 404


class TestAnalyzeResume:
    @staticmethod
    def _analysis(resume):
        return SimpleNamespace(
            resume_id=resume.id, summary="A great engineer.", strengths=["Python"], issues=[],
            role_suggestions=["Backend Dev"], improvement_tips=["Add more projects"],
            section_quality={"skills": 0.9}, llm_enhanced=False, parse_error=None,
        )

    def test_access_rules(self, check_access, resume_a, candidate_a, candidate_b, mock_services):
        mock_services.resume_analysis.analyse.return_value = self._analysis(resume_a)
        r = check_access("POST", f"{BASE}/{resume_a.id}/analyze", owner=candidate_a, other=candidate_b,
                         json={"force_refresh": False})
        body = r.get_json()
        assert body["success"] is True
        assert {"resume_id", "summary", "role_suggestions"} <= set(body["data"])

    def test_non_owner_does_not_trigger_analysis(
        self, client, db, resume_a, candidate_b, headers_for, mock_services
    ):
        client.post(f"{BASE}/{resume_a.id}/analyze", json={}, headers=headers_for(candidate_b))
        mock_services.resume_analysis.analyse.assert_not_called()

    def test_a_busy_parser_on_reparse_is_503_with_retry_after(
        self, client, db, resume_a, candidate_a, headers_for, mock_services
    ):
        from unittest.mock import patch

        from app.core.exceptions import ResumeParserBusy

        resume_a.storage_key = "stored-key"
        db.session.commit()
        mock_services.resume_parser.parse_bytes.side_effect = ResumeParserBusy()
        with patch("app.services.storage_service.LocalStorageBackend.download_bytes", return_value=b"%PDF-1.4"):
            r = client.post(f"{BASE}/{resume_a.id}/analyze", json={"force_refresh": True},
                            headers=headers_for(candidate_a))

        assert r.status_code == 503
        assert r.headers["Retry-After"] == str(ResumeParserBusy.retry_after)
        assert r.get_json()["error"]["error_code"] == "PARSER_BUSY"

    def test_nonexistent_resume_404(self, client, db, candidate_a, headers_for, mock_services):
        r = client.post(f"{BASE}/no-such/analyze", json={}, headers=headers_for(candidate_a))
        assert r.status_code == 404


class TestScorePreview:
    @staticmethod
    def _mock_scoring(mock_services, final_score=0.75):
        """score_raw returns the same keys as AtsScorerService.score_raw."""
        from app.services.explainability_engine import ExplanationResult
        mock_services.ats_scorer.score_raw.return_value = {
            "final_score": final_score, "semantic_score": 0.0, "keyword_score": 0.8,
            "experience_score": 0.7, "section_quality_score": 0.6,
            "semantic_available": False, "semantic_component_scores": {},
            "weights_used": {"semantic": 0.4, "keyword": 0.35, "experience": 0.15, "section": 0.1},
        }
        mock_services.explainability.explain.return_value = ExplanationResult()

    def test_access_rules(self, check_access, resume_a, job_a, candidate_a, candidate_b, mock_services):
        self._mock_scoring(mock_services)
        r = check_access("GET", f"{BASE}/{resume_a.id}/score-preview?job_id={job_a.id}",
                         owner=candidate_a, other=candidate_b)
        assert r.get_json()["data"]["preview"] is True

    def test_a_recruiter_cannot_preview(self, client, db, resume_a, job_a, recruiter_a, headers_for, mock_services):
        r = client.get(f"{BASE}/{resume_a.id}/score-preview?job_id={job_a.id}", headers=headers_for(recruiter_a))
        assert r.status_code == 403

    def test_missing_job_id_400(self, client, db, resume_a, candidate_a, headers_for):
        r = client.get(f"{BASE}/{resume_a.id}/score-preview", headers=headers_for(candidate_a))
        assert r.status_code == 400
        assert r.get_json()["error"]["error_code"] == "MISSING_PARAM"

    def test_nonexistent_resume_404(self, client, db, job_a, candidate_a, headers_for):
        r = client.get(f"{BASE}/no-such/score-preview?job_id={job_a.id}", headers=headers_for(candidate_a))
        assert r.status_code == 404

    def test_nonexistent_job_404(self, client, db, resume_a, candidate_a, headers_for):
        r = client.get(f"{BASE}/{resume_a.id}/score-preview?job_id=ghost-job", headers=headers_for(candidate_a))
        assert r.status_code == 404

    def test_a_job_that_is_not_active_is_404(
        self, client, db, resume_a, draft_job_a, candidate_a, headers_for, mock_services
    ):
        self._mock_scoring(mock_services)
        r = client.get(f"{BASE}/{resume_a.id}/score-preview?job_id={draft_job_a.id}",
                       headers=headers_for(candidate_a))
        assert r.status_code == 404


class TestSetActive:
    def test_access_rules(self, check_access, resume_a, candidate_a, candidate_b):
        r = check_access("PATCH", f"{BASE}/{resume_a.id}/set-active", owner=candidate_a, other=candidate_b)
        assert r.get_json()["data"]["is_active"] is True

    def test_other_candidates_resumes_are_untouched(
        self, client, db, resume_a, resume_b, candidate_a, headers_for
    ):
        client.patch(f"{BASE}/{resume_a.id}/set-active", headers=headers_for(candidate_a))
        db.session.refresh(resume_b)
        assert resume_b.is_active is True


class TestGenerateSummary:
    def test_access_rules(self, check_access, resume_a, candidate_a, candidate_b, mock_services):
        mock_services.groq.available = True
        mock_services.groq.generate_resume_summary.return_value = {"summary": "A concise summary."}
        r = check_access("POST", f"{BASE}/{resume_a.id}/generate-summary",
                         owner=candidate_a, other=candidate_b, json={})
        assert r.get_json()["data"]["summary"] == "A concise summary."

    def test_non_owner_does_not_trigger_the_llm(
        self, client, db, resume_a, candidate_b, headers_for, mock_services
    ):
        mock_services.groq.available = True
        client.post(f"{BASE}/{resume_a.id}/generate-summary", json={}, headers=headers_for(candidate_b))
        mock_services.groq.generate_resume_summary.assert_not_called()


class TestRewriteSuggestions:
    @pytest.fixture(autouse=True)
    def _groq(self, mock_services):
        mock_services.groq.available = True
        mock_services.keyword_matcher.get_skill_breakdown.return_value = {"missing": []}

    def test_access_rules(self, check_access, resume_a, job_a, candidate_a, candidate_b):
        r = check_access("POST", f"{BASE}/{resume_a.id}/rewrite-suggestions",
                         owner=candidate_a, other=candidate_b, json={"job_id": job_a.id})
        assert r.get_json()["data"]["job_title"] == "Job A"

    def test_another_users_resume_is_403_not_404(self, client, db, resume_a, job_a, candidate_b, headers_for):
        r = client.post(f"{BASE}/{resume_a.id}/rewrite-suggestions", json={"job_id": job_a.id},
                        headers=headers_for(candidate_b))
        assert r.status_code == 403

    def test_missing_job_id_400(self, client, db, resume_a, candidate_a, headers_for):
        r = client.post(f"{BASE}/{resume_a.id}/rewrite-suggestions", json={}, headers=headers_for(candidate_a))
        assert r.status_code == 400

    def test_a_job_that_is_not_active_is_404(self, client, db, resume_a, draft_job_a, candidate_a, headers_for):
        r = client.post(f"{BASE}/{resume_a.id}/rewrite-suggestions", json={"job_id": draft_job_a.id},
                        headers=headers_for(candidate_a))
        assert r.status_code == 404
