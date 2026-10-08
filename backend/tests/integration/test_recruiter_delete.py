"""
tests/integration/test_recruiter_delete.py

Deleting a recruiter is a soft delete and never removes their jobs.
"""
BASE = "/api/v1/recruiters"


def _recruiter_auth(recruiter):
    from app.core.security import create_tokens
    access_token, _, _ = create_tokens(recruiter.id, "recruiter")
    return {"Authorization": f"Bearer {access_token}"}


def test_delete_soft_deletes_and_keeps_jobs(client, db, sample_recruiter, sample_job):
    from app.models.job import Job

    r = client.delete(f"{BASE}/{sample_recruiter.id}", headers=_recruiter_auth(sample_recruiter))

    assert r.status_code == 204
    db.session.refresh(sample_recruiter)
    assert sample_recruiter.is_deleted is True
    job = db.session.get(Job, sample_job.id)
    assert job is not None
    assert job.is_deleted is False
    assert job.recruiter_id == sample_recruiter.id


def test_deleting_twice_returns_404(client, db, sample_recruiter):
    headers = _recruiter_auth(sample_recruiter)
    assert client.delete(f"{BASE}/{sample_recruiter.id}", headers=headers).status_code == 204
    r = client.delete(f"{BASE}/{sample_recruiter.id}", headers=headers)
    assert r.status_code == 404
    assert r.get_json()["error"]["error_code"] == "RECRUITER_NOT_FOUND"


def test_hard_delete_does_not_cascade_to_jobs(db, sample_recruiter, sample_job):
    # Even a hard delete of the row must not delete jobs through the ORM
    # cascade; the FK (ON DELETE SET NULL) just unlinks them.
    from app.models.job import Job

    db.session.delete(sample_recruiter)
    db.session.flush()
    db.session.expire_all()

    job = db.session.get(Job, sample_job.id)
    assert job is not None
    assert job.recruiter_id is None
