"""
app/models/mixins.py

Reusable SQLAlchemy ORM mixins.

FIXES APPLIED:
  MX-01 — SoftDeleteMixin.to_dict() had a falsy condition bug.

    Original:
        if exclude and "deleted_at" not in exclude:
            ...

    Problem: when `exclude=None` (the default), `if exclude` is False so the
    `deleted_at` field was NEVER serialised into the output dict, even though
    callers expected it to be present.

    Fix: changed the guard to:
        if not exclude or "deleted_at" not in exclude:
            ...

    This means:
      • exclude=None  → include deleted_at  (was broken — now fixed)
      • exclude=set() → include deleted_at  (unchanged)
      • exclude={"deleted_at"} → skip it    (unchanged — callers who
                                              explicitly exclude it still work)
"""

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import db

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Soft Delete Mixin
# ─────────────────────────────────────────────────────────────────────────────

class SoftDeleteMixin:
    """
    Adds soft-delete capability to a model.

    Columns added:
      - is_deleted (Boolean, default False, indexed)
      - deleted_at (DateTime, nullable)

    Methods:
      - soft_delete():  Mark as deleted (does NOT call db.session.delete).
      - restore():      Undelete a record.
      - is_alive (property): True when not soft-deleted.

    Important:
      Soft-deleted records are NOT filtered out automatically.
      Repository methods must apply .filter(Model.is_deleted == False)
      unless explicitly querying deleted records.
      This is intentional — the mixin stays dumb, the query logic stays
      in the repository where it belongs.
    """

    __abstract__ = True

    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,     # Indexed — nearly every query filters on this
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        db.DateTime(timezone=True),
        nullable=True,
    )

    def soft_delete(self) -> None:
        """
        Mark this record as deleted.

        Does NOT flush or commit — caller controls the transaction.
        """
        self.is_deleted = True
        self.deleted_at = datetime.now(timezone.utc)
        logger.info(
            "Record soft-deleted",
            extra={"model": self.__class__.__name__, "id": getattr(self, "id", "?")},
        )

    def restore(self) -> None:
        """
        Restore a soft-deleted record.

        Does NOT flush or commit — caller controls the transaction.
        """
        self.is_deleted = False
        self.deleted_at = None
        logger.info(
            "Record restored",
            extra={"model": self.__class__.__name__, "id": getattr(self, "id", "?")},
        )

    @property
    def is_alive(self) -> bool:
        """True when the record is NOT soft-deleted."""
        return not self.is_deleted

    def to_dict(self, exclude: set[str] | None = None) -> dict[str, Any]:
        """
        Override to_dict to include soft-delete fields.

        FIX MX-01: Original guard was `if exclude and "deleted_at" not in exclude`
        which evaluated to False when exclude=None (the default), so deleted_at
        was silently omitted from ALL default serialisations.

        Corrected guard: `if not exclude or "deleted_at" not in exclude`
          • exclude=None  → always include deleted_at  ← was broken, now fixed
          • exclude={"deleted_at"} → still excluded     ← callers that opt out
        """
        d = super().to_dict(exclude=exclude)  # type: ignore[misc]
        # FIX MX-01: was `if exclude and ...` — should be `if not exclude or ...`
        if not exclude or "deleted_at" not in exclude:
            val = self.deleted_at
            d["deleted_at"] = val.isoformat() if val else None
        return d


# ─────────────────────────────────────────────────────────────────────────────
# Searchable Mixin
# ─────────────────────────────────────────────────────────────────────────────

class SearchableMixin:
    """
    Adds a class-method helper for building ILIKE search filters.

    Usage:
        query = Job.search_filter(query, search_term, [Job.title, Job.company])
    """

    __abstract__ = True

    @classmethod
    def search_filter(cls, query, term: str, columns: list):
        """
        Apply ILIKE filter across multiple text columns (OR logic).

        Works on both PostgreSQL (uses native ILIKE) and SQLite
        (SQLAlchemy translates ILIKE to LIKE, case-insensitive by default).

        Args:
            query:   Active SQLAlchemy query object.
            term:    Search string (stripped, lowercased internally).
            columns: List of mapped column attributes to search across.

        Returns:
            Filtered query.
        """
        if not term or not term.strip():
            return query

        pattern = f"%{term.strip()}%"
        from sqlalchemy import or_
        return query.filter(
            or_(*[col.ilike(pattern) for col in columns])
        )