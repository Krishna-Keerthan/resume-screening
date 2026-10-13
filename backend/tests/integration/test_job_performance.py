"""
GET /api/v1/jobs/<id>/performance through the real RecruiterAnalyticsService
and real repositories; nothing in the analytics path is mocked.
"""
from types import SimpleNamespace

import pytest

from app.models.ats_score import AtsScore
from app.repositories import ApplicationRepository, AtsScoreRepository, JobRepository
from app.services.recruiter_analytics_service import RecruiterAnalyticsService

BASE = "/api/v1/jobs"


@pytest.fixture()
def real_analytics(app):
    """Replace only the service container; the analytics service in it is the real one."""
    original = app.extensions.get("services")
    app.extensions["services"] = SimpleNamespace(
        recruiter_analytics=RecruiterAnalyticsService(
            job_repo=JobRepository(),
            application_repo=ApplicationRepository(),
            ats_score_repo=AtsScoreRepository(),
        )
    )
    yield
    app.extensions["services"] = original


def _get(client, job_id, recruiter, headers_for):
    return client.get(f"{BASE}/{job_id}/performance", headers=headers_for(recruiter))


def test_a_job_with_no_applicants_returns_zeroed_stats(
    client, real_analytics, job_a, recruiter_a, headers_for
):
    r = _get(client, job_a.id, recruiter_a, headers_for)

    assert r.status_code == 200, r.get_json()
    data = r.get_json()["data"]
    assert data["job_id"] == job_a.id
    assert data["applicant_count"] == 0
    assert data["avg_ats_score"] == 0.0
    assert data["stage_breakdown"] == {}


def test_a_job_with_a_scored_applicant_reports_its_stats(
    client, db, real_analytics, job_a, recruiter_a, resume_a, application_a, headers_for
):
    db.session.add(AtsScore(resume_id=resume_a.id, job_id=job_a.id, final_score=0.8, score_label="excellent"))
    db.session.commit()

    r = _get(client, job_a.id, recruiter_a, headers_for)

    assert r.status_code == 200, r.get_json()
    data = r.get_json()["data"]
    assert data["avg_ats_score"] == 0.8
    assert sum(data["stage_breakdown"].values()) == 1


def test_a_missing_job_is_404(client, real_analytics, recruiter_a, headers_for):
    assert _get(client, "phantom", recruiter_a, headers_for).status_code == 404


def test_a_service_that_raises_is_a_500(client, db, job_a, recruiter_a, headers_for, mock_services):
    mock_services.recruiter_analytics.get_job_performance.side_effect = RuntimeError("db down")

    r = _get(client, job_a.id, recruiter_a, headers_for)

    assert r.status_code == 500
    assert "db down" not in r.get_data(as_text=True)


def test_an_empty_service_result_is_200_with_zeroed_stats(
    client, db, job_a, recruiter_a, headers_for, mock_services
):
    mock_services.recruiter_analytics.get_job_performance.return_value = {}

    r = _get(client, job_a.id, recruiter_a, headers_for)

    assert r.status_code == 200, r.get_json()
    data = r.get_json()["data"]
    assert data["job_id"] == job_a.id
    assert data["applicant_count"] == 0
    assert data["avg_ats_score"] == 0.0
    assert data["stage_breakdown"] == {}


def test_the_service_lets_repository_errors_propagate(app):
    class _Broken:
        def count_by_stage(self, **kwargs):
            raise RuntimeError("db down")

    svc = RecruiterAnalyticsService(
        job_repo=SimpleNamespace(get_by_id=lambda job_id: SimpleNamespace(title="t", applicant_count=0, quality_score=None)),
        application_repo=_Broken(),
        ats_score_repo=None,
    )
    with pytest.raises(RuntimeError):
        svc.get_job_performance("j1")
