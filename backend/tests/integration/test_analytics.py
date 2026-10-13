"""
tests/integration/test_analytics.py

Integration tests for /api/v1/analytics/* endpoints.

Every route is recruiter-only and reports on the authenticated recruiter;
there is no recruiter_id parameter.
"""
import pytest
from unittest.mock import MagicMock

BASE = "/api/v1/analytics"

ROUTES = ["dashboard", "pipeline", "score-distribution", "skills-demand", "top-jobs"]


def _dashboard_mock(recruiter_id="r-id"):
    m = MagicMock()
    m.recruiter_id       = recruiter_id
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


@pytest.fixture()
def stub_analytics(mock_services):
    analytics = mock_services.recruiter_analytics
    analytics.get_dashboard.return_value = _dashboard_mock()
    analytics.get_pipeline.return_value = {"applied": 10, "reviewed": 5, "hired": 2}
    return analytics


@pytest.mark.parametrize("route", ROUTES)
class TestAccess:
    def test_access_rules(self, check_access, stub_analytics, route, recruiter_a, candidate_a):
        check_access("GET", f"{BASE}/{route}", owner=recruiter_a, other=candidate_a)


class TestIdentityComesFromTheToken:
    def test_dashboard_is_built_for_the_caller(
        self, client, db, stub_analytics, recruiter_a, recruiter_b, headers_for
    ):
        r = client.get(f"{BASE}/dashboard?recruiter_id={recruiter_b.id}", headers=headers_for(recruiter_a))
        assert r.status_code == 200
        stub_analytics.get_dashboard.assert_called_once_with(recruiter_a.id)

    def test_pipeline_is_built_for_the_caller(
        self, client, db, stub_analytics, recruiter_a, recruiter_b, headers_for
    ):
        client.get(f"{BASE}/pipeline?recruiter_id={recruiter_b.id}", headers=headers_for(recruiter_a))
        stub_analytics.get_pipeline.assert_called_once_with(recruiter_a.id)

    @pytest.mark.parametrize("route", ["score-distribution", "skills-demand", "top-jobs"])
    def test_dashboard_derived_routes_are_built_for_the_caller(
        self, client, db, stub_analytics, route, recruiter_a, recruiter_b, headers_for
    ):
        client.get(f"{BASE}/{route}?recruiter_id={recruiter_b.id}", headers=headers_for(recruiter_a))
        stub_analytics.get_dashboard.assert_called_once_with(recruiter_a.id)


class TestDashboard:
    def test_response_shape(self, client, db, stub_analytics, recruiter_a, headers_for):
        data = client.get(f"{BASE}/dashboard", headers=headers_for(recruiter_a)).get_json()["data"]
        for key in ("total_jobs", "active_jobs", "total_applications", "total_hired", "pipeline_funnel"):
            assert key in data


class TestPipeline:
    def test_returns_stage_breakdown(self, client, db, stub_analytics, recruiter_a, headers_for):
        body = client.get(f"{BASE}/pipeline", headers=headers_for(recruiter_a)).get_json()
        assert body["data"] == {"applied": 10, "reviewed": 5, "hired": 2}


class TestScoreDistribution:
    def test_score_tiers_present(self, client, db, stub_analytics, recruiter_a, headers_for):
        dist = client.get(f"{BASE}/score-distribution", headers=headers_for(recruiter_a)).get_json()["data"]
        for tier in ("excellent", "good", "fair", "weak"):
            assert tier in dist


class TestSkillsDemand:
    def test_returns_skills_list(self, client, db, stub_analytics, recruiter_a, headers_for):
        body = client.get(f"{BASE}/skills-demand?top_n=5", headers=headers_for(recruiter_a)).get_json()
        assert body["data"]["skills"] == [{"skill": "Python", "count": 30}]
        assert body["data"]["recruiter_id"] == recruiter_a.id


class TestTopJobs:
    def test_data_is_list(self, client, db, stub_analytics, recruiter_a, headers_for):
        body = client.get(f"{BASE}/top-jobs", headers=headers_for(recruiter_a)).get_json()
        assert body["data"]["jobs"] == []
