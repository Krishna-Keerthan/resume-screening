"""
app/core/database.py

SQLAlchemy database initialisation and base model class.

JWT Auth changes (Phase 7):
  - _import_models() includes refresh_token so create_all() / Alembic
    autogenerate sees the RefreshToken table.

Design:
  - db is the single Flask-SQLAlchemy extension instance.
  - BaseModel adds audit columns (id, created_at, updated_at) and
    shared helpers (to_dict, save, delete) to every model.
  - init_db() wires the extension to the Flask app during create_app().
  - SQLite is used in dev/testing; PostgreSQL in production.
    The only change required is DATABASE_URL — no code changes.

Usage:
    from app.core.database import db, BaseModel

    class Resume(BaseModel):
        __tablename__ = "resumes"
        candidate_id = db.Column(db.String(36), ...)
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


# ─────────────────────────────────────────────────────────────────────────────
# Declarative base with SQLAlchemy 2.x style
# ─────────────────────────────────────────────────────────────────────────────

class _Base(DeclarativeBase):
    """Internal declarative base — not imported directly outside this module."""
    pass


# Single db instance — shared across all models
db = SQLAlchemy(model_class=_Base)

# Generic TypeVar for repository return types
from typing import TypeVar
ModelT = TypeVar("ModelT", bound="BaseModel")


# ─────────────────────────────────────────────────────────────────────────────
# Base Model — audit fields + convenience helpers
# ─────────────────────────────────────────────────────────────────────────────

class BaseModel(db.Model):  # type: ignore[name-defined]
    """
    Abstract base for all ORM models.

    Provides:
      - id:         UUID primary key (string representation for portability).
      - created_at: UTC timestamp set on INSERT.
      - updated_at: UTC timestamp updated on every UPDATE.
      - save():     Flush model to the database session.
      - delete():   Remove model from the database.
      - to_dict():  Return a plain dict of all column values (override in subclass
                    to exclude sensitive / large fields).
    """

    __abstract__ = True

    # ── Primary key ──────────────────────────────────────────────────────────
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        nullable=False,
    )

    # ── Audit timestamps ─────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def save(self) -> "BaseModel":
        """
        Add this model to the session and flush to the DB.

        Does NOT commit — the caller controls transaction boundaries.
        For explicit commit: db.session.commit()
        """
        db.session.add(self)
        db.session.flush()
        return self

    def delete(self) -> None:
        """Remove this model from the session."""
        db.session.delete(self)

    def to_dict(self, exclude: set[str] | None = None) -> dict[str, Any]:
        """
        Serialise all mapped columns to a plain Python dict.

        Args:
            exclude: Set of column names to omit (e.g. {"raw_text"} in list views).

        Returns:
            Dict with ISO-formatted timestamps, UUID strings, etc.
        """
        exclude = exclude or set()
        result: dict[str, Any] = {}

        for col in self.__table__.columns:
            if col.name in exclude:
                continue
            value = getattr(self, col.name, None)
            if isinstance(value, datetime):
                value = value.isoformat()
            result[col.name] = value

        return result

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.id!r}>"


# ─────────────────────────────────────────────────────────────────────────────
# Initialisation
# ─────────────────────────────────────────────────────────────────────────────

def init_db(app: Flask) -> None:
    """
    Bind SQLAlchemy to the Flask app and create tables if they don't exist.

    Called from create_app() after all models have been imported.
    In production, use Alembic migrations instead of create_all().

    Args:
        app: The configured Flask application instance.
    """
    db.init_app(app)

    with app.app_context():
        # Import all models here to ensure they are registered with SQLAlchemy
        # before create_all() is called.
        _import_models()
        db.create_all()

    app.logger.info("Database initialised.")


def _import_models() -> None:
    """
    Trigger model imports so SQLAlchemy discovers them before create_all()
    and Alembic autogenerate can detect all tables.

    This must stay in sync as new models are added.
    Import order doesn't matter — SQLAlchemy resolves FK dependencies.
    """
    # pylint: disable=import-outside-toplevel
    from app.models import (  # noqa: F401
        candidate,
        recruiter,
        job,
        resume,
        application,
        ats_score,
        refresh_token,   # ← Phase 7: JWT refresh token ledger
    )