"""
tests/unit/test_db_isolation.py  —  Guarantees of the `db` fixture.

Fixtures, the test body and request handlers must share one transaction,
and everything (including commits) must be rolled back after each test.
"""
from app.models.recruiter import Recruiter

PROBE_EMAIL = "isolation-probe@example.com"


def test_fixture_rows_are_visible_in_the_test(db, sample_recruiter):
    assert db.session.get(Recruiter, sample_recruiter.id) is not None


def test_fixture_rows_are_visible_to_requests(client, sample_job):
    r = client.get(f"/api/v1/jobs/{sample_job.id}")
    assert r.status_code == 200


def test_commit_in_one_test_writes_probe(db):
    Recruiter(full_name="Probe", email=PROBE_EMAIL, company_name="Probe").save()
    db.session.commit()


def test_commit_in_previous_test_was_rolled_back(db):
    assert db.session.query(Recruiter).filter_by(email=PROBE_EMAIL).count() == 0
