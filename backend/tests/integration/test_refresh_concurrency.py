"""
Concurrent refreshes with one cookie, on real connections.

The shared `db` fixture funnels every request through one connection, which
cannot show a race, so this test commits real rows and drives the endpoint
from several threads. It needs row locking, so it runs on PostgreSQL only.
"""

import threading

import pytest

from app.core.database import db as _db

BASE = "/api/v1/auth"
THREADS = 6


@pytest.fixture()
def committed_candidate(app):
    from app.models.candidate import Candidate
    from app.models.refresh_token import RefreshToken
    from tests.conftest import _new_candidate

    if _db.engine.dialect.name != "postgresql":
        pytest.skip("needs concurrent connections with row locks (set TEST_DATABASE_URL to PostgreSQL)")

    candidate = _new_candidate("race")
    user_id = candidate.id
    yield candidate
    _db.session.rollback()
    _db.session.query(RefreshToken).filter_by(user_id=user_id).delete()
    _db.session.query(Candidate).filter_by(id=user_id).delete()
    _db.session.commit()


def test_concurrent_refreshes_with_one_cookie_have_exactly_one_winner(
    app, committed_candidate, account_password
):
    client = app.test_client(use_cookies=False)
    login = client.post(f"{BASE}/login", json={
        "email": committed_candidate.email, "password": account_password, "role": "candidate",
    })
    assert login.status_code == 200
    raw = next(
        h for h in login.headers.getlist("Set-Cookie") if h.startswith("refresh_token=")
    ).split(";", 1)[0].split("=", 1)[1]

    barrier = threading.Barrier(THREADS)
    results = []

    def worker():
        with app.app_context():
            c = app.test_client(use_cookies=False)
            barrier.wait()
            r = c.post(f"{BASE}/refresh", headers={"Cookie": f"refresh_token={raw}"})
            results.append((r.status_code, (r.get_json() or {}).get("error", {}).get("error_code")))

    threads = [threading.Thread(target=worker) for _ in range(THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    statuses = sorted(status for status, _ in results)
    assert statuses == [200] + [401] * (THREADS - 1), results
    assert {code for status, code in results if status == 401} == {"TOKEN_REUSED"}
