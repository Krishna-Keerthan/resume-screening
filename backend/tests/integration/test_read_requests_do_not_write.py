"""
A GET, HEAD or OPTIONS request never commits and never writes.

The after-request hook used to commit every 200, so each successful read paid an extra
COMMIT round trip, and a session left unusable by an earlier failed flush turned a 200 into
a 500 when the commit raised PendingRollbackError.
"""
import logging
import uuid

import pytest
from sqlalchemy import event
from sqlalchemy import orm as sa_orm
from sqlalchemy.exc import PendingRollbackError

from app.models.candidate import Candidate

_WRITES = ("INSERT", "UPDATE", "DELETE")


@pytest.fixture()
def commits(db):
    seen = []
    listener = lambda session: seen.append(1)          # noqa: E731
    event.listen(sa_orm.Session, "after_commit", listener)
    yield seen
    event.remove(sa_orm.Session, "after_commit", listener)


@pytest.fixture()
def statements(db):
    seen = []

    def record(conn, cursor, statement, parameters, context, executemany):
        seen.append(" ".join(statement.split()))

    event.listen(db.engine, "before_cursor_execute", record)
    yield seen
    event.remove(db.engine, "before_cursor_execute", record)


def _get_rules(app):
    return sorted(
        (r for r in app.url_map.iter_rules() if r.rule.startswith("/api/") and "GET" in r.methods),
        key=lambda r: r.rule,
    )


def _fill(rule, ids):
    missing = rule.arguments - set(ids)
    assert not missing, f"{rule.rule}: teach this test an id for {sorted(missing)}"
    return rule.rule.replace("<", "{").replace(">", "}").format(**ids)


@pytest.fixture()
def ids(db, candidate_a, recruiter_a, job_a, resume_a, application_a):
    db.session.commit()        # a read rolls back, so the fixtures must be saved first
    return {
        "candidate_id": candidate_a.id, "recruiter_id": recruiter_a.id, "job_id": job_a.id,
        "resume_id": resume_a.id, "application_id": application_a.id, "score_id": str(uuid.uuid4()),
    }


def test_the_commit_counter_sees_a_write_request(client, commits):
    body = {"full_name": "New Person", "email": "new.person@example.com", "password": "SecureP@ss1"}

    assert client.post("/api/v1/auth/register/candidate", json=body).status_code == 201
    assert commits


def test_no_get_route_commits_or_writes(app, client, headers_for, candidate_a, recruiter_a, ids,
                                        commits, statements, caplog, monkeypatch):
    caplog.set_level(logging.ERROR)
    # The health probe opens its own connection. On the in-memory SQLite these tests use, that
    # is the test's connection, and closing it would roll back the test's data.
    monkeypatch.setitem(app.extensions, "database_probe", lambda: True)
    rules = _get_rules(app)
    assert len(rules) >= 25

    for rule in rules:
        url = _fill(rule, ids)
        for user in (candidate_a, recruiter_a):
            commits.clear()
            statements.clear()
            client.get(url, headers=headers_for(user))
            writes = [s for s in statements if s.startswith(_WRITES)]
            assert not commits, f"GET {url} as {type(user).__name__} committed"
            assert not writes, f"GET {url} as {type(user).__name__} wrote: {writes[0][:120]}"
    assert "unsaved changes" not in caplog.text


@pytest.mark.parametrize("method", ["head", "options"])
def test_head_and_options_do_not_commit(client, commits, method):
    getattr(client, method)("/api/v1/health")

    assert not commits


def _break_the_session(db):
    """A failed flush leaves the session waiting for a rollback, as a request that hit a DB error does."""
    db.session.add(Candidate())
    with pytest.raises(Exception):
        db.session.flush()


def test_a_failed_flush_leaves_the_session_raising_pending_rollback_error(db):
    _break_the_session(db)

    with pytest.raises(PendingRollbackError):
        db.session.execute(db.text("SELECT 1"))


@pytest.mark.parametrize("url", ["/api/v1/health", "/api/v1/health/services"])
def test_a_read_with_an_unusable_session_is_still_a_200(client, db, url):
    _break_the_session(db)

    assert client.get(url).status_code == 200
