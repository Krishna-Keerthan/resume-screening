"""RefreshTokenRepository owns every refresh-token query; the model only builds and inspects rows."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.refresh_token import RefreshToken
from app.repositories.refresh_token import RefreshTokenRepository


@pytest.fixture()
def repo(db):
    return RefreshTokenRepository()


def _new(repo, user_id="user-1", role="candidate"):
    jti = str(uuid.uuid4())
    raw = f"raw-{jti}"
    row = repo.create_token(
        jti=jti, raw_token=raw, user_id=user_id, role=role,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    return row, raw


def test_create_token_stores_only_the_hash(repo):
    row, raw = _new(repo)
    assert row.token_hash == RefreshToken.hash_token(raw)
    assert raw not in (row.token_hash, row.jti)
    assert repo.get_by_jti(row.jti) is row
    assert repo.get_by_hash(raw) is row


def test_claim_succeeds_once_and_then_reports_the_token_as_taken(repo, db):
    row, _ = _new(repo)

    assert repo.claim(row.jti) is True
    assert repo.claim(row.jti) is False

    db.session.refresh(row)
    assert row.revoked is True
    assert row.revoked_at is not None


def test_claim_of_an_unknown_jti_is_false(repo):
    assert repo.claim("no-such-jti") is False


def test_claim_does_not_touch_other_tokens(repo, db):
    mine, _ = _new(repo)
    other, _ = _new(repo)
    repo.claim(mine.jti)
    db.session.refresh(other)
    assert other.revoked is False


def test_revoke_all_for_user_revokes_only_that_users_live_tokens(repo, db):
    a1, _ = _new(repo, user_id="user-a")
    a2, _ = _new(repo, user_id="user-a")
    already, _ = _new(repo, user_id="user-a")
    repo.revoke(already)
    b, _ = _new(repo, user_id="user-b")

    assert repo.revoke_all_for_user("user-a") == 2

    for row in (a1, a2, b, already):
        db.session.refresh(row)
    assert (a1.revoked, a2.revoked, already.revoked, b.revoked) == (True, True, True, False)


@pytest.mark.parametrize("name", ["get_by_jti", "get_by_hash", "revoke_all_for_user", "claim"])
def test_the_model_has_no_session_touching_helpers(name):
    assert not hasattr(RefreshToken, name)
