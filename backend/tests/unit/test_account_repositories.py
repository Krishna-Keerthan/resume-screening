"""get_active_by_id: only an existing, active, non-deleted account is returned."""

import pytest

from app.repositories.candidate import CandidateRepository
from app.repositories.recruiter import RecruiterRepository


@pytest.fixture(params=["candidate", "recruiter"])
def account(request, candidate_a, recruiter_a):
    if request.param == "candidate":
        return CandidateRepository(), candidate_a
    return RecruiterRepository(), recruiter_a


def test_returns_a_live_account(account):
    repo, user = account
    assert repo.get_active_by_id(user.id) is user


def test_returns_none_for_a_deleted_account(account, db):
    repo, user = account
    user.soft_delete()
    db.session.flush()
    assert repo.get_active_by_id(user.id) is None


def test_returns_none_for_an_inactive_account(account, db):
    repo, user = account
    user.is_active = False
    db.session.flush()
    assert repo.get_active_by_id(user.id) is None


def test_returns_none_for_an_unknown_id(account):
    repo, _ = account
    assert repo.get_active_by_id("does-not-exist") is None
