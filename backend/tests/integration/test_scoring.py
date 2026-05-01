
"""
tests/integration/test_scoring.py

Integration tests for /api/v1/scores/* endpoints.
"""
import json
import pytest
from unittest.mock import MagicMock

BASE = "/api/v1/scores"


def _score_result_mock():
    m = MagicMock()
    m.id                   = "mock-ats-id"
    m.resume_id            = "r-id"
    m.job_id               = "j-id"
    m.final_score          = 0.78
    m.score_label          = "good"
    m.keyword_score        = 0.80
    m.semantic_score       = 0.70
    m.experience_score     = 0.75
    m.section_quality_score = 0.65
    m.matched_skills       = ["Python", "Flask"]
    m.missing_skills       = ["Kubernetes"]
    m.extra_skills         = ["FastAPI"]
    m.explanation          = {"strengths": [], "gaps": []}
    m.error                = None
    return m


class TestMatchEndpoint:
    def test_preview_mode_200(self, client, db, sample_resume, sample_job, mock_services):
        mock_services.ats_scorer.score_raw.return_value = {
            "final_score": 0.75, "score_label": "good",
            "matched_skills": ["Python"], "missing_skills": [],
        }
        r = client.post(
            f"{BASE}/match",
            data=json.dumps({
                "resume_id":   sample_resume.id,
                "job_id":      sample_job.id,
                "save_result": False,
            }),
            content_type="application/json",
        )
        assert r.status_code == 200
        body = r.get_json()
        assert body["success"] is True
        assert body["data"]["preview"] is True

    def test_persist_mode_201(self, client, db, sample_resume, sample_job, mock_services):
        mock_services.ats_scorer.score_resume_job.return_value = _score_result_mock()
        r = client.post(
            f"{BASE}/match",
            data=json.dumps({
                "resume_id":   sample_resume.id,
                "job_id":      sample_job.id,
                "save_result": True,
            }),
            content_type="application/json",
        )
        assert r.status_code in (200, 201)

    def test_missing_resume_id_400(self, client, db, sample_job, mock_services):
        r = client.post(
            f"{BASE}/match",
            data=json.dumps({"job_id": sample_job.id}),
            content_type="application/json",
        )
        assert r.status_code == 400

    def test_missing_job_id_400(self, client, db, sample_resume, mock_services):
        r = client.post(
            f"{BASE}/match",
            data=json.dumps({"resume_id": sample_resume.id}),
            content_type="application/json",
        )
        assert r.status_code == 400

    def test_nonexistent_resume_404(self, client, db, sample_job, mock_services):
        r = client.post(
            f"{BASE}/match",
            data=json.dumps({"resume_id": "no-such-resume", "job_id": sample_job.id}),
            content_type="application/json",
        )
        assert r.status_code == 404

    def test_nonexistent_job_404(self, client, db, sample_resume, mock_services):
        r = client.post(
            f"{BASE}/match",
            data=json.dumps({"resume_id": sample_resume.id, "job_id": "no-such-job"}),
            content_type="application/json",
        )
        assert r.status_code == 404


class TestRankCandidatesEndpoint:
    def test_returns_200(self, client, db, sample_job, mock_services):
        mock_services.candidate_ranking.rank_for_job.return_value = MagicMock(
            candidates=[], total=0, page=1, per_page=20,
            score_stats=MagicMock(mean=0.0),
        )
        r = client.post(
            f"{BASE}/rank-candidates",
            data=json.dumps({"job_id": sample_job.id}),
            content_type="application/json",
        )
        assert r.status_code == 200

    def test_nonexistent_job_404(self, client, db, mock_services):
        r = client.post(
            f"{BASE}/rank-candidates",
            data=json.dumps({"job_id": "ghost-job"}),
            content_type="application/json",
        )
        assert r.status_code == 404

    def test_missing_job_id_400(self, client, db, mock_services):
        r = client.post(
            f"{BASE}/rank-candidates",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert r.status_code == 400


class TestJobRecommendationsEndpoint:
    def test_returns_200(self, client, db, sample_resume, mock_services):
        mock_services.job_recommendation.recommend_jobs_for_resume.return_value = MagicMock(
            recommendations=[], resume_id=sample_resume.id, total=0,
        )
        r = client.post(
            f"{BASE}/job-recommendations",
            data=json.dumps({"resume_id": sample_resume.id, "top_n": 5}),
            content_type="application/json",
        )
        assert r.status_code == 200

    def test_nonexistent_resume_404(self, client, db, mock_services):
        r = client.post(
            f"{BASE}/job-recommendations",
            data=json.dumps({"resume_id": "no-such"}),
            content_type="application/json",
        )
        assert r.status_code == 404

    def test_missing_resume_id_400(self, client, db, mock_services):
        r = client.post(
            f"{BASE}/job-recommendations",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert r.status_code == 400


class TestSkillGapEndpoint:
    def test_with_job_id_200(self, client, db, sample_resume, sample_job, mock_services):
        mock_services.ats_scorer.skill_gap.return_value = {
            "matched_skills": ["Python"], "missing_skills": ["Kubernetes"], "extra_skills": [],
        }
        r = client.post(
            f"{BASE}/skill-gap",
            data=json.dumps({"resume_id": sample_resume.id, "job_id": sample_job.id}),
            content_type="application/json",
        )
        assert r.status_code == 200
        body = r.get_json()
        assert "matched_skills" in body["data"]
        assert "missing_skills" in body["data"]

    def test_nonexistent_resume_404(self, client, db, sample_job, mock_services):
        r = client.post(
            f"{BASE}/skill-gap",
            data=json.dumps({"resume_id": "ghost", "job_id": sample_job.id}),
            content_type="application/json",
        )
        assert r.status_code == 404

    def test_nonexistent_job_404(self, client, db, sample_resume, mock_services):
        r = client.post(
            f"{BASE}/skill-gap",
            data=json.dumps({"resume_id": sample_resume.id, "job_id": "ghost-job"}),
            content_type="application/json",
        )
        assert r.status_code == 404


class TestListScores:
    def test_returns_200(self, client, db):
        assert client.get(f"{BASE}/").status_code == 200

    def test_pagination_meta(self, client, db):
        meta = client.get(f"{BASE}/").get_json()["meta"]
        assert "total" in meta

    def test_filter_by_resume_id(self, client, db, sample_resume):
        body = client.get(f"{BASE}/?resume_id={sample_resume.id}").get_json()
        assert body["success"] is True

    def test_filter_by_min_score(self, client, db):
        body = client.get(f"{BASE}/?min_score=0.7").get_json()
        assert body["success"] is True

    def test_invalid_min_score_400(self, client, db):
        r = client.get(f"{BASE}/?min_score=not-a-number")
        assert r.status_code == 400