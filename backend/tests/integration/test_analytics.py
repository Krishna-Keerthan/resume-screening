
"""
tests/integration/test_analytics.py

Integration tests for /api/v1/analytics/* endpoints.
All analytics routes require recruiter_id query param.
"""
import pytest
from unittest.mock import MagicMock

BASE = "/api/v1/analytics"


def _dashboard_mock():
    m = MagicMock()
    m.recruiter_id       = "r-id"
    m.total_jobs         = 5
    m.active_jobs        = 3
    m.total_applications = 42
    m.total_hired        = 10
    m.avg_score          = 0.72
    m.pipeline_funnel    = {"applied": 42, "hired": 10}
    m.top_jobs           = []
    m.score_distribution = {"excellent": 5, "good": 20, "fair": 12, "weak": 5}
    m.skills_demand      = [{"skill": "Python", "count": 30}]
    return m


class TestDashboard:
    def test_missing_recruiter_id_400(self, client, db):
        r = client.get(f"{BASE}/dashboard")
        assert r.status_code == 400

    def test_nonexistent_recruiter_404(self, client, db, mock_services):
        r = client.get(f"{BASE}/dashboard?recruiter_id=no-such-recruiter")
        assert r.status_code == 404

    def test_returns_200_for_valid_recruiter(self, client, db, sample_recruiter, mock_services):
        mock_services.recruiter_analytics.get_dashboard.return_value = _dashboard_mock()
        r = client.get(f"{BASE}/dashboard?recruiter_id={sample_recruiter.id}")
        assert r.status_code == 200

    def test_response_shape(self, client, db, sample_recruiter, mock_services):
        mock_services.recruiter_analytics.get_dashboard.return_value = _dashboard_mock()
        body = client.get(f"{BASE}/dashboard?recruiter_id={sample_recruiter.id}").get_json()
        data = body["data"]
        assert "total_jobs" in data
        assert "active_jobs" in data
        assert "total_applications" in data
        assert "total_hired" in data
        assert "pipeline_funnel" in data


class TestPipeline:
    def test_missing_recruiter_id_400(self, client, db):
        assert client.get(f"{BASE}/pipeline").status_code == 400

    def test_nonexistent_recruiter_404(self, client, db, mock_services):
        assert client.get(f"{BASE}/pipeline?recruiter_id=nobody").status_code == 404

    def test_returns_200(self, client, db, sample_recruiter, mock_services):
        mock_services.recruiter_analytics.get_pipeline.return_value = {
            "applied": 10, "reviewed": 5, "hired": 2
        }
        r = client.get(f"{BASE}/pipeline?recruiter_id={sample_recruiter.id}")
        assert r.status_code == 200

    def test_returns_stage_breakdown(self, client, db, sample_recruiter, mock_services):
        mock_services.recruiter_analytics.get_pipeline.return_value = {
            "applied": 10, "reviewed": 5, "hired": 2
        }
        body = client.get(f"{BASE}/pipeline?recruiter_id={sample_recruiter.id}").get_json()
        assert "pipeline" in body["data"]


class TestScoreDistribution:
    def test_missing_recruiter_id_400(self, client, db):
        assert client.get(f"{BASE}/score-distribution").status_code == 400

    def test_nonexistent_recruiter_404(self, client, db, mock_services):
        assert client.get(f"{BASE}/score-distribution?recruiter_id=nobody").status_code == 404

    def test_returns_200(self, client, db, sample_recruiter, mock_services):
        mock_services.recruiter_analytics.get_score_distribution.return_value = {
            "excellent": 5, "good": 20, "fair": 12, "weak": 5
        }
        r = client.get(f"{BASE}/score-distribution?recruiter_id={sample_recruiter.id}")
        assert r.status_code == 200

    def test_score_tiers_present(self, client, db, sample_recruiter, mock_services):
        mock_services.recruiter_analytics.get_score_distribution.return_value = {
            "excellent": 5, "good": 20, "fair": 12, "weak": 5
        }
        body = client.get(
            f"{BASE}/score-distribution?recruiter_id={sample_recruiter.id}"
        ).get_json()
        dist = body["data"]["score_distribution"]
        for tier in ["excellent", "good", "fair", "weak"]:
            assert tier in dist


class TestSkillsDemand:
    def test_missing_recruiter_id_400(self, client, db):
        assert client.get(f"{BASE}/skills-demand").status_code == 400

    def test_returns_200(self, client, db, sample_recruiter, mock_services):
        mock_services.recruiter_analytics.get_skills_demand.return_value = [
            {"skill": "Python", "count": 15},
            {"skill": "Docker", "count": 10},
        ]
        r = client.get(f"{BASE}/skills-demand?recruiter_id={sample_recruiter.id}")
        assert r.status_code == 200

    def test_returns_skills_list(self, client, db, sample_recruiter, mock_services):
        mock_services.recruiter_analytics.get_skills_demand.return_value = [
            {"skill": "Python", "count": 15},
        ]
        body = client.get(
            f"{BASE}/skills-demand?recruiter_id={sample_recruiter.id}"
        ).get_json()
        assert "skills" in body["data"]
        assert isinstance(body["data"]["skills"], list)

    def test_top_n_param(self, client, db, sample_recruiter, mock_services):
        mock_services.recruiter_analytics.get_skills_demand.return_value = []
        r = client.get(f"{BASE}/skills-demand?recruiter_id={sample_recruiter.id}&top_n=5")
        assert r.status_code == 200


class TestTopJobs:
    def test_missing_recruiter_id_400(self, client, db):
        assert client.get(f"{BASE}/top-jobs").status_code == 400

    def test_returns_200(self, client, db, sample_recruiter, mock_services):
        mock_services.recruiter_analytics.get_top_jobs.return_value = []
        r = client.get(f"{BASE}/top-jobs?recruiter_id={sample_recruiter.id}")
        assert r.status_code == 200

    def test_data_is_list(self, client, db, sample_recruiter, mock_services):
        mock_services.recruiter_analytics.get_top_jobs.return_value = []
        body = client.get(
            f"{BASE}/top-jobs?recruiter_id={sample_recruiter.id}"
        ).get_json()