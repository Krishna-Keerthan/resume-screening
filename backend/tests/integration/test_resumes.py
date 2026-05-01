
"""
tests/integration/test_resumes.py

Integration tests for /api/v1/resumes/* endpoints.
"""
import pytest

BASE = "/api/v1/resumes"


class TestListResumes:
    def test_returns_200(self, client, db):
        assert client.get(f"{BASE}/").status_code == 200

    def test_success_envelope(self, client, db):
        body = client.get(f"{BASE}/").get_json()
        assert body["success"] is True

    def test_data_is_list(self, client, db):
        assert isinstance(client.get(f"{BASE}/").get_json()["data"], list)

    def test_pagination_meta(self, client, db):
        meta = client.get(f"{BASE}/").get_json()["meta"]
        assert "total" in meta and "page" in meta

    def test_filter_by_candidate_id(self, client, db, sample_resume, sample_candidate):
        body = client.get(f"{BASE}/?candidate_id={sample_candidate.id}").get_json()
        ids = [r["id"] for r in body["data"]]
        assert sample_resume.id in ids

    def test_filter_by_parse_status(self, client, db, sample_resume):
        body = client.get(f"{BASE}/?parse_status=success").get_json()
        assert body["success"] is True
        assert all(r["parse_status"] == "success" for r in body["data"])

    def test_invalid_parse_status_400(self, client, db):
        r = client.get(f"{BASE}/?parse_status=unknown_status")
        assert r.status_code == 400


class TestGetResume:
    def test_returns_200(self, client, db, sample_resume):
        assert client.get(f"{BASE}/{sample_resume.id}").status_code == 200

    def test_correct_data(self, client, db, sample_resume):
        body = client.get(f"{BASE}/{sample_resume.id}").get_json()
        assert body["data"]["id"] == sample_resume.id
        assert body["data"]["candidate_id"] == sample_resume.candidate_id
        assert body["data"]["parse_status"] == "success"

    def test_skills_present(self, client, db, sample_resume):
        body = client.get(f"{BASE}/{sample_resume.id}").get_json()
        assert isinstance(body["data"]["skills"], list)
        assert "Python" in body["data"]["skills"]

    def test_experience_years(self, client, db, sample_resume):
        body = client.get(f"{BASE}/{sample_resume.id}").get_json()
        assert body["data"]["total_experience_years"] == 6.0

    def test_nonexistent_404(self, client, db):
        r = client.get(f"{BASE}/no-such-resume")
        assert r.status_code == 404
        assert r.get_json()["error"]["error_code"] == "RESUME_NOT_FOUND"


class TestDeleteResume:
    def test_returns_204(self, client, db, sample_resume):
        assert client.delete(f"{BASE}/{sample_resume.id}").status_code == 204

    def test_deleted_is_404(self, client, db, sample_resume):
        client.delete(f"{BASE}/{sample_resume.id}")
        assert client.get(f"{BASE}/{sample_resume.id}").status_code == 404

    def test_nonexistent_404(self, client, db):
        assert client.delete(f"{BASE}/phantom-resume").status_code == 404


class TestAnalyzeResume:
    def test_returns_200_with_mock(self, client, db, sample_resume, mock_services):
        from unittest.mock import MagicMock
        result = MagicMock()
        result.resume_id        = sample_resume.id
        result.summary          = "A great engineer."
        result.strengths        = ["Python", "Flask"]
        result.issues           = []
        result.role_suggestions = ["Backend Dev"]
        result.improvement_tips = ["Add more projects"]
        result.section_quality  = {"skills": 0.9}
        result.llm_enhanced     = False
        result.parse_error      = None
        mock_services.resume_analysis.analyse.return_value = result

        import json
        r = client.post(
            f"{BASE}/{sample_resume.id}/analyze",
            data=json.dumps({"force_refresh": False}),
            content_type="application/json",
        )
        assert r.status_code == 200

    def test_analysis_response_shape(self, client, db, sample_resume, mock_services):
        from unittest.mock import MagicMock
        result = MagicMock()
        result.resume_id        = sample_resume.id
        result.summary          = "Test summary."
        result.strengths        = []
        result.issues           = []
        result.role_suggestions = []
        result.improvement_tips = []
        result.section_quality  = {}
        result.llm_enhanced     = False
        result.parse_error      = None
        mock_services.resume_analysis.analyse.return_value = result

        import json
        body = client.post(
            f"{BASE}/{sample_resume.id}/analyze",
            data=json.dumps({}),
            content_type="application/json",
        ).get_json()

        assert body["success"] is True
        assert "resume_id" in body["data"]
        assert "summary" in body["data"]
        assert "role_suggestions" in body["data"]

    def test_nonexistent_resume_404(self, client, db, mock_services):
        import json
        r = client.post(
            f"{BASE}/no-such/analyze",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert r.status_code == 404


class TestScorePreview:
    def test_missing_job_id_400(self, client, db, sample_resume):
        r = client.get(f"{BASE}/{sample_resume.id}/score-preview")
        assert r.status_code == 400
        assert r.get_json()["error"]["error_code"] == "MISSING_PARAM"

    def test_nonexistent_resume_404(self, client, db, sample_job):
        r = client.get(f"{BASE}/no-such/score-preview?job_id={sample_job.id}")
        assert r.status_code == 404

    def test_nonexistent_job_404(self, client, db, sample_resume):
        r = client.get(f"{BASE}/{sample_resume.id}/score-preview?job_id=ghost-job")
        assert r.status_code == 404

    def test_returns_200_with_mock(self, client, db, sample_resume, sample_job, mock_services):
        mock_services.ats_scorer.score_raw.return_value = {
            "final_score": 0.75, "score_label": "good",
            "matched_skills": ["Python"], "missing_skills": [],
            "keyword_score": 0.8, "experience_score": 0.7,
            "semantic_score": 0.0, "section_quality_score": 0.6,
        }
        r = client.get(f"{BASE}/{sample_resume.id}/score-preview?job_id={sample_job.id}")
        assert r.status_code == 200

    def test_preview_true_in_response(self, client, db, sample_resume, sample_job, mock_services):
        mock_services.ats_scorer.score_raw.return_value = {
            "final_score": 0.5, "score_label": "fair",
            "matched_skills": [], "missing_skills": [],
        }
        body = client.get(f"{BASE}/{sample_resume.id}/score-preview?job_id={sample_job.id}").get_json()
        assert body["data"]["preview"] is True