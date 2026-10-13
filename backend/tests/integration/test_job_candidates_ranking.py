"""
GET /api/v1/jobs/<id>/candidates through the real CandidateRankingService
and real repositories; nothing in the ranking path is mocked.
"""
from types import SimpleNamespace

import pytest

from app.models.application import Application
from app.models.ats_score import AtsScore
from app.repositories import ApplicationRepository, AtsScoreRepository, CandidateRepository
from app.services.candidate_ranking_service import CandidateRankingService

BASE = "/api/v1/jobs"


@pytest.fixture()
def real_ranking(app):
    """Replace only the service container; the ranking service in it is the real one."""
    original = app.extensions.get("services")
    app.extensions["services"] = SimpleNamespace(
        candidate_ranking=CandidateRankingService(
            application_repo=ApplicationRepository(),
            ats_score_repo=AtsScoreRepository(),
            candidate_repo=CandidateRepository(),
        )
    )
    yield
    app.extensions["services"] = original


@pytest.fixture()
def two_scored_applicants(
    db, job_a, candidate_a, resume_a, candidate_b, resume_b, application_a
):
    """Candidate A (strong) and candidate B (weak) have both applied to job A."""
    db.session.add_all([
        Application(candidate_id=candidate_b.id, job_id=job_a.id, resume_id=resume_b.id),
        AtsScore(resume_id=resume_a.id, job_id=job_a.id, final_score=0.91, score_label="excellent"),
        AtsScore(resume_id=resume_b.id, job_id=job_a.id, final_score=0.32, score_label="weak"),
    ])
    db.session.commit()


def _get(client, job, recruiter, headers_for, query=""):
    r = client.get(f"{BASE}/{job.id}/candidates{query}", headers=headers_for(recruiter))
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def test_applicants_are_ranked_best_first(
    client, real_ranking, two_scored_applicants, job_a, recruiter_a, candidate_a, candidate_b, headers_for
):
    body = _get(client, job_a, recruiter_a, headers_for)

    assert [c["candidate_id"] for c in body["data"]] == [candidate_a.id, candidate_b.id]
    assert [c["final_score"] for c in body["data"]] == [0.91, 0.32]
    assert [c["score_label"] for c in body["data"]] == ["excellent", "weak"]
    assert body["data"][0]["name"] == candidate_a.full_name
    assert body["meta"]["total"] == 2


def test_min_score_filters_out_weak_applicants(
    client, real_ranking, two_scored_applicants, job_a, recruiter_a, candidate_a, headers_for
):
    body = _get(client, job_a, recruiter_a, headers_for, "?min_score=0.5")
    assert [c["candidate_id"] for c in body["data"]] == [candidate_a.id]
    assert body["meta"]["total"] == 1


def test_stage_filter_applies(
    client, real_ranking, two_scored_applicants, job_a, recruiter_a, candidate_b, db, headers_for
):
    application = db.session.query(Application).filter_by(candidate_id=candidate_b.id).one()
    application.stage = "reviewed"
    db.session.commit()

    body = _get(client, job_a, recruiter_a, headers_for, "?stage=reviewed")
    assert [c["candidate_id"] for c in body["data"]] == [candidate_b.id]


def test_a_deleted_applicant_is_not_listed(
    client, real_ranking, two_scored_applicants, job_a, recruiter_a, candidate_a, candidate_b, db, headers_for
):
    candidate_b.soft_delete()
    db.session.commit()
    body = _get(client, job_a, recruiter_a, headers_for)
    assert [c["candidate_id"] for c in body["data"]] == [candidate_a.id]


def test_a_job_with_no_applicants_returns_an_empty_list(client, real_ranking, job_a, recruiter_a, headers_for):
    body = _get(client, job_a, recruiter_a, headers_for)
    assert body["data"] == []
    assert body["meta"]["total"] == 0


def test_another_recruiter_cannot_see_the_ranking(
    client, real_ranking, two_scored_applicants, job_a, recruiter_b, headers_for
):
    assert client.get(f"{BASE}/{job_a.id}/candidates", headers=headers_for(recruiter_b)).status_code == 403
