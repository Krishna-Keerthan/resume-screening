"""
app/repositories/refresh_token.py

Repository for RefreshToken — isolates all DB operations for refresh tokens.

WHY THIS FILE EXISTS (FIX RT-01):
  The original codebase had no RefreshTokenRepository. All DB operations
  (get_by_jti, get_by_hash, revoke_all_for_user, revoke) lived directly on
  the RefreshToken model class, which violates the 4-layer architecture:

    API → Service → Repository → Model

  Model methods should be pure data containers and business logic helpers.
  They must NOT call db.session directly — that's the repository's job.

  The specific violation (RT-01): RefreshToken.revoke() and
  revoke_all_for_user() called db.session.flush() inside the model, coupling
  the model to the ORM session lifecycle. This made the model untestable
  without a live DB session.

  This file extracts all session operations into a proper repository.
  The model keeps its classmethod helpers (hash_token, create, is_valid)
  as pure logic — no session calls.

  auth.py should import and use RefreshTokenRepository instead of calling
  model classmethods that touch the session.
"""

import logging
from datetime import datetime, timezone

from app.core.database import db
from app.models.refresh_token import RefreshToken
from app.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    """Repository for RefreshToken model — all session I/O lives here."""

    model = RefreshToken

    # ── Lookups ───────────────────────────────────────────────────────────────

    def get_by_jti(self, jti: str) -> RefreshToken | None:
        """
        Fetch a RefreshToken by its JWT ID claim.

        Used during token refresh (to validate the incoming refresh token)
        and during logout (to mark the token as revoked).
        """
        return (
            db.session.query(RefreshToken)
            .filter_by(jti=jti)
            .first()
        )

    def get_by_hash(self, raw_token: str) -> RefreshToken | None:
        """
        Fetch by raw token value — computes the SHA-256 hash internally.

        Prefer get_by_jti() when the JTI claim is available; this method
        performs a hash computation on every call.
        """
        token_hash = RefreshToken.hash_token(raw_token)
        return (
            db.session.query(RefreshToken)
            .filter_by(token_hash=token_hash)
            .first()
        )

    def get_active_for_user(
        self,
        user_id: str,
        role: str | None = None,
    ) -> list[RefreshToken]:
        """
        Return all non-revoked, non-expired tokens for a user.

        Used to display active sessions in a "manage devices" UI.
        """
        now   = datetime.now(timezone.utc)
        query = (
            db.session.query(RefreshToken)
            .filter(
                RefreshToken.user_id    == user_id,
                RefreshToken.revoked    == False,
                RefreshToken.expires_at >  now,
            )
        )
        if role:
            query = query.filter(RefreshToken.role == role)
        return query.order_by(RefreshToken.created_at.desc()).all()

    # ── Mutations ─────────────────────────────────────────────────────────────

    def create_token(
        self,
        jti: str,
        raw_token: str,
        user_id: str,
        role: str,
        expires_at: datetime,
    ) -> RefreshToken:
        """
        Persist a new RefreshToken row.

        Builds the instance via RefreshToken.create() (pure factory),
        adds it to the session, and flushes to assign the PK.

        Args:
            jti:        JWT ID claim from the token pair.
            raw_token:  The raw refresh token string (hashed before storage).
            user_id:    UUID of the owning user.
            role:       'candidate' | 'recruiter'.
            expires_at: Hard expiry datetime (timezone-aware).

        Returns:
            The flushed (but not committed) RefreshToken instance.
        """
        rt = RefreshToken.create(
            jti=jti,
            raw_token=raw_token,
            user_id=user_id,
            role=role,
            expires_at=expires_at,
        )
        db.session.add(rt)
        db.session.flush()
        logger.debug("RefreshToken created for user=%s jti=%s", user_id, jti)
        return rt

    def revoke(self, token: RefreshToken) -> None:
        """
        Mark a single token as revoked.

        FIX RT-01: Original code called db.session.flush() inside the model
        method. Session lifecycle is the repository's responsibility.
        The model's revoke() helper now only mutates fields; flushing is done
        here.
        """
        token.revoked    = True
        token.revoked_at = datetime.now(timezone.utc)
        db.session.add(token)
        db.session.flush()
        logger.debug("RefreshToken revoked jti=%s user=%s", token.jti, token.user_id)

    def revoke_all_for_user(self, user_id: str) -> int:
        """
        Revoke every active refresh token for a user (logout-all).

        FIX RT-01: Original code lived on the model class and called
        db.session.flush() inside a model method. Moved here.

        Returns:
            Number of rows updated.
        """
        now = datetime.now(timezone.utc)
        tokens = (
            db.session.query(RefreshToken)
            .filter_by(user_id=user_id, revoked=False)
            .all()
        )
        for rt in tokens:
            rt.revoked    = True
            rt.revoked_at = now
            db.session.add(rt)
        db.session.flush()
        logger.info(
            "All refresh tokens revoked for user=%s count=%d", user_id, len(tokens)
        )
        return len(tokens)

    # ── Maintenance ───────────────────────────────────────────────────────────

    def prune_expired(self) -> int:
        """
        Hard-delete rows that are both revoked and past their expiry.

        Should be called by a nightly cron or scheduled task to keep the
        table small. Safe to run at any time — non-revoked tokens are never
        deleted regardless of expiry.

        Returns:
            Number of rows deleted.
        """
        now = datetime.now(timezone.utc)
        deleted = (
            db.session.query(RefreshToken)
            .filter(
                RefreshToken.revoked    == True,
                RefreshToken.expires_at <  now,
            )
            .delete(synchronize_session="fetch")
        )
        db.session.flush()
        logger.info("Pruned %d expired refresh token rows", deleted)
        return deleted