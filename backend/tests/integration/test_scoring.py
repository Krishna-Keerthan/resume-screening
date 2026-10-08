
"""
tests/integration/test_scoring.py

Integration tests for /api/v1/scores/* endpoints.
"""
import json
import pytest
from unittest.mock import MagicMock, create_autospec

BASE = "/api/v1/scores"


def _score_result():
    from app.services.ats_scorer import ScoringResult
    return ScoringResult(
        resume_id="r-id",
        job_id="j-id",
        final_score=0.78,
        score_label="good",
        semantic_score=0.70,
        keyword_score=0.80,
        experience_score=0.75,
        section_quality_score=0.65,
        semantic_available=True,
        matched_skills=["Python", "Flask"],
        missing_skills=["Kubernetes"],
        extra_skills=["FastAPI"],
        ats_score_id="mock-ats-id",
    )


def _raw_score():
    """Same keys AtsScorerService.score_raw returns."""
    return {
        "final_score": 0.75, "semantic_score": 0.0, "keyword_score": 0.8,
        "experience_score": 0.7, "section_quality_score": 0.6,
        "semantic_available": False, "semantic_component_scores": {},
        "weights_used": {"semantic": 0.4, "keyword": 0.35, "experience": 0.15, "section": 0.1},
    }


class TestMatchEndpoint:
    def test_preview_mode_200(self, client, db, sample_resume, sample_job, mock_services):
        mock_services.ats_scorer.score_raw.return_value = _raw_score()
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
        assert body["data"]["saved"] is False

    def test_preview_calls_score_raw_with_its_real_signature(
        self, client, db, sample_resume, sample_job, mock_services,
    ):
        from app.services.ats_scorer import AtsScorerService
        mock_services.ats_scorer = create_autospec(AtsScorerService, instance=True)
        mock_services.ats_scorer.score_raw.return_value = _raw_score()
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
        kwargs = mock_services.ats_scorer.score_raw.call_args.kwargs
        assert kwargs["job_experience_years"] == sample_job.experience_years

    def test_persist_mode_201(self, client, db, sample_resume, sample_job, mock_services):
        mock_services.ats_scorer.score_resume_job.return_value = _score_result()
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
        from app.services.candidate_ranking_service import RankingResult
        mock_services.candidate_ranking.rank_for_job.return_value = RankingResult(
            candidates=[], total=0, page=1, per_page=20, score_stats={"mean": 0.0},
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
        mock_services.keyword_matcher.get_skill_breakdown.return_value = {
            "matched": ["python"], "missing": ["kubernetes"], "extra": [],
        }
        r = client.post(
            f"{BASE}/skill-gap",
            data=json.dumps({"resume_id": sample_resume.id, "job_id": sample_job.id}),
            content_type="application/json",
        )
        assert r.status_code == 200
        body = r.get_json()
        assert body["data"]["matched"] == ["python"]
        assert body["data"]["missing"] == ["kubernetes"]

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