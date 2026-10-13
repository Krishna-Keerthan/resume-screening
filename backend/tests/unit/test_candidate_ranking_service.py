"""Candidate ranking only lists applicants whose accounts are alive."""

import pytest

from app.models.application import Application
from app.repositories import ApplicationRepository, AtsScoreRepository, CandidateRepository
from app.services.candidate_ranking_service import CandidateRankingService


@pytest.fixture()
def ranking():
    return CandidateRankingService(
        application_repo=ApplicationRepository(),
        ats_score_repo=AtsScoreRepository(),
        candidate_repo=CandidateRepository(),
    )


@pytest.fixture()
def applicants(db, job_a, candidate_a, resume_a, candidate_b, resume_b):
    """Candidates A and B have both applied to job A."""
    for candidate, resume in ((candidate_a, resume_a), (candidate_b, resume_b)):
        Application(candidate_id=candidate.id, job_id=job_a.id, resume_id=resume.id).save()
    db.session.flush()
    return candidate_a, candidate_b


def _ranked_ids(ranking, job):
    result = ranking.rank_for_job(job_id=job.id, page=1, per_page=20, min_score=0.0)
    return {c.candidate_id for c in result.candidates}, result.total


def test_lists_every_live_applicant(ranking, job_a, applicants):
    candidate_a, candidate_b = applicants
    ids, total = _ranked_ids(ranking, job_a)
    assert ids == {candidate_a.id, candidate_b.id}
    assert total == 2


def test_excludes_a_deleted_applicant(ranking, job_a, applicants, db):
    candidate_a, candidate_b = applicants
    candidate_b.soft_delete()
    db.session.flush()
    ids, total = _ranked_ids(ranking, job_a)
    assert ids == {candidate_a.id}
    assert total == 1


def test_excludes_an_inactive_applicant(ranking, job_a, applicants, db):
    candidate_a, candidate_b = applicants
    candidate_b.is_active = False
    db.session.flush()
    ids, total = _ranked_ids(ranking, job_a)
    assert ids == {candidate_a.id}
    assert total == 1
