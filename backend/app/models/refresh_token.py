"""
app/models/refresh_token.py

Persisted refresh-token ledger.

Why store refresh tokens?
  Stateless access tokens are self-validating (signature + exp).  But refresh
  tokens must be revocable without a global secret rotation.  Storing a SHA-256
  hash of each refresh token allows:
    • Logout              — mark a single token as revoked
    • Logout everywhere   — revoke all tokens for a user
    • Token rotation      — old token revoked when new pair is issued
    • Breach response     — bulk-revoke by user or issued-before timestamp

Only the SHA-256 hash is stored — the raw token string is never persisted,
so a DB breach cannot replay tokens.

Table: refresh_tokens
─────────────────────
  id           UUID PK
  jti          unique string  — the 'jti' claim from the JWT payload
                                (links access + refresh in the same family)
  token_hash   string         — SHA-256(raw_refresh_token)
  user_id      string         — FK-ish; not a hard FK to keep tables decoupled
  role         string         — 'candidate' | 'recruiter'
  expires_at   datetime       — hard expiry; cron can prune rows older than this
  revoked      bool           — True after logout or rotation
  revoked_at   datetime?      — when it was revoked (audit trail)
  created_at   datetime
"""

import hashlib
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import BaseModel, db


class RefreshToken(BaseModel):
    """
    One row per active (or recently revoked) refresh token.

    Rows are never hard-deleted while the token has not expired so that
    revocation history is available.  A nightly cron / Alembic-based cleanup
    job should prune rows where expires_at < NOW() and revoked=True.
    """

    __tablename__ = "refresh_tokens"

    # ── Token identity ────────────────────────────────────────────────────────
    jti: Mapped[str] = mapped_column(
        String(36),
        unique=True,
        nullable=False,
        index=True,
        comment="JWT ID from the token payload — shared by access + refresh in a pair",
    )
    token_hash: Mapped[str] = mapped_column(
        String(64),         # SHA-256 hex digest is always 64 chars
        nullable=False,
        unique=True,
        comment="SHA-256(raw refresh token string) — never store the raw token",
    )

    # ── Owner ─────────────────────────────────────────────────────────────────
    user_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
        comment="UUID of the candidate or recruiter who owns this token",
    )
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="'candidate' | 'recruiter'",
    )

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Hard expiry — matches the JWT exp claim",
    )
    revoked: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ── Composite indexes ─────────────────────────────────────────────────────
    __table_args__ = (
        # Fast revocation check for a specific user
        Index("ix_refresh_tokens_user_revoked", "user_id", "revoked"),
        # Pruning query: DELETE WHERE expires_at < NOW() AND revoked = True
        Index("ix_refresh_tokens_expires_revoked", "expires_at", "revoked"),
    )

    # ── Class-level helpers ───────────────────────────────────────────────────

    @classmethod
    def hash_token(cls, raw_token: str) -> str:
        """Return the SHA-256 hex digest of a raw refresh token string."""
        return hashlib.sha256(raw_token.encode()).hexdigest()

    @classmethod
    def create(
        cls,
        jti: str,
        raw_token: str,
        user_id: str,
        role: str,
        expires_at: datetime,
    ) -> "RefreshToken":
        """
        Build (but do not save) a RefreshToken from a raw token string.

        The caller must call .save() or db.session.add() + flush.
        """
        rt = cls()
        rt.jti        = jti
        rt.token_hash = cls.hash_token(raw_token)
        rt.user_id    = user_id
        rt.role       = role
        rt.expires_at = expires_at
        rt.revoked    = False
        return rt

    @classmethod
    def get_by_jti(cls, jti: str) -> "RefreshToken | None":
        """Fetch by JTI — used during token refresh and logout."""
        return db.session.query(cls).filter_by(jti=jti).first()

    @classmethod
    def get_by_hash(cls, raw_token: str) -> "RefreshToken | None":
        """Fetch by raw token — computes hash internally."""
        token_hash = cls.hash_token(raw_token)
        return db.session.query(cls).filter_by(token_hash=token_hash).first()

    @classmethod
    def revoke_all_for_user(cls, user_id: str) -> int:
        """
        Revoke every active refresh token for a user.
        Returns the number of rows updated.
        """
        now = datetime.now(timezone.utc)
        updated = (
            db.session.query(cls)
            .filter_by(user_id=user_id, revoked=False)
            .all()
        )
        for rt in updated:
            rt.revoked    = True
            rt.revoked_at = now
        db.session.flush()
        return len(updated)

    def revoke(self) -> None:
        """Mark this token as revoked."""
        self.revoked    = True
        self.revoked_at = datetime.now(timezone.utc)
        

    def is_valid(self) -> bool:
        """True if the token has not been revoked and has not expired."""
        if self.revoked:
            return False

        expires = self.expires_at

        # 🔥 SQLite returns naive datetime — fix it safely
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)

        return datetime.now(timezone.utc) < expires

    def to_dict(self, exclude: set[str] | None = None) -> dict[str, Any]:
        """Never include token_hash in serialised output."""
        d = super().to_dict(exclude=exclude)
        d.pop("token_hash", None)   # never leak the hash
        return d
    