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


# ─── get_by_email / email_exists ──────────────────────────────────────────────

from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.recruiter import Recruiter


def _make_candidate(email):
    c = Candidate(full_name="Someone", email=email, password_hash=hash_password("x"))
    c.save()
    return c


def _make_recruiter(email):
    r = Recruiter(full_name="Someone", email=email, company_name="Co", password_hash=hash_password("x"))
    r.save()
    return r


@pytest.fixture(params=["candidate", "recruiter"])
def accounts(request, db):
    """(repository, make(email)) for each account type."""
    if request.param == "candidate":
        return CandidateRepository(), _make_candidate
    return RecruiterRepository(), _make_recruiter


def test_get_by_email_ignores_case_and_surrounding_whitespace(accounts, db):
    repo, make = accounts
    stored = make("Mixed.Case@Example.com")
    db.session.flush()
    assert repo.get_by_email("  mixed.CASE@example.COM ") is stored


def test_get_by_email_returns_none_for_an_unknown_address(accounts, db):
    repo, make = accounts
    make("known@example.com")
    db.session.flush()
    assert repo.get_by_email("other@example.com") is None


def test_underscore_in_an_email_matches_only_itself(accounts, db):
    repo, make = accounts
    plain = make("axb@example.com")
    literal = make("a_b@example.com")
    db.session.flush()
    assert repo.get_by_email("a_b@example.com") is literal
    assert repo.get_by_email("axb@example.com") is plain
    assert repo.email_exists("a_c@example.com") is False


def test_percent_in_an_email_matches_only_itself(accounts, db):
    repo, make = accounts
    make("alice@example.com")
    db.session.flush()
    assert repo.get_by_email("%@example.com") is None
    assert repo.get_by_email("alice%") is None
    assert repo.email_exists("%") is False


def test_email_exists_still_sees_deleted_accounts(accounts, db):
    repo, make = accounts
    gone = make("gone@example.com")
    gone.soft_delete()
    db.session.flush()
    assert repo.email_exists("GONE@example.com") is True
