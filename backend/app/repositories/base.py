
"""
app/repositories/base.py

Generic typed repository base class.

Design principles:
  - Generic[T] — works with any SQLAlchemy model inheriting from BaseModel.
  - All methods operate on db.session — no session management here.
    Session lifecycle is managed at the request/transaction boundary.
  - list_paginated() returns (items, total_count) — total is the
    unpaged count for building pagination meta.
  - Soft-delete aware — models with SoftDeleteMixin are filtered
    automatically unless include_deleted=True is passed.
  - No business logic — pure data access.

Usage:
    from app.repositories.base import BaseRepository
    from app.models.job import Job

    class JobRepository(BaseRepository[Job]):
        model = Job

        def get_active_by_recruiter(self, recruiter_id: str) -> list[Job]:
            return (
                self.base_query()
                .filter_by(recruiter_id=recruiter_id, status="active")
                .all()
            )
"""

import logging
from typing import Any, Generic, TypeVar

from app.core.database import BaseModel, db
from app.core.exceptions import NotFoundError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class BaseRepository(Generic[T]):
    """
    Generic CRUD repository.

    Concrete repositories must set the class-level `model` attribute:
        class JobRepository(BaseRepository[Job]):
            model = Job
    """

    model: type[T]  # Set by subclass

    # ── Core read operations ──────────────────────────────────────────────────

    def get_by_id(self, record_id: str) -> T | None:
        """
        Fetch a record by primary key.

        Args:
            record_id: UUID string primary key.

        Returns:
            Model instance or None if not found.
        """
        return db.session.get(self.model, record_id)

    def get_by_id_or_raise(self, record_id: str) -> T:
        """
        Fetch a record by primary key, raising NotFoundError if absent.

        Args:
            record_id: UUID string primary key.

        Returns:
            Model instance.

        Raises:
            NotFoundError: If no record with that ID exists.
        """
        record = self.get_by_id(record_id)
        if record is None:
            raise NotFoundError(
                f"{self.model.__name__} '{record_id}' not found.",
                details={
                    "model":  self.model.__name__,
                    "id":     record_id,
                },
            )
        return record

    def get_by_field(self, field: str, value: Any) -> T | None:
        """
        Fetch the first record matching field=value.

        Args:
            field: Column name string.
            value: Value to match.

        Returns:
            First matching model instance, or None.
        """
        return (
            db.session.query(self.model)
            .filter(getattr(self.model, field) == value)
            .first()
        )

    def exists(self, record_id: str) -> bool:
        """Return True if a record with this ID exists."""
        return self.get_by_id(record_id) is not None

    def count(self, **filters: Any) -> int:
        """Return total record count, optionally filtered by kwargs."""
        return (
            db.session.query(self.model)
            .filter_by(**filters)
            .count()
        )

    # ── Query builder ─────────────────────────────────────────────────────────

    def base_query(self, include_deleted: bool = False):
        """
        Return a base SQLAlchemy query for this model.

        Automatically filters soft-deleted records unless include_deleted=True.

        Args:
            include_deleted: If True, include soft-deleted records.

        Returns:
            SQLAlchemy Query object.
        """
        query = db.session.query(self.model)

        # Apply soft-delete filter if the model uses SoftDeleteMixin
        from app.models.mixins import SoftDeleteMixin
        if issubclass(self.model, SoftDeleteMixin) and not include_deleted:
            query = query.filter(self.model.is_deleted == False)  # noqa: E712

        return query

    # ── Paginated list ────────────────────────────────────────────────────────

    def list_paginated(
        self,
        page: int = 1,
        limit: int = 20,
        order_by=None,
        include_deleted: bool = False,
        **filters: Any,
    ) -> tuple[list[T], int]:
        """
        Fetch a paginated list of records.

        Args:
            page:            1-based page number.
            limit:           Records per page.
            order_by:        SQLAlchemy column expression for ORDER BY.
                             Defaults to created_at DESC.
            include_deleted: Include soft-deleted records.
            **filters:       Column=value equality filters.

        Returns:
            (items, total) tuple where total is the unpaged count.
        """
        query = self.base_query(include_deleted=include_deleted)

        if filters:
            # Filter out None values — skip optional filters
            active_filters = {k: v for k, v in filters.items() if v is not None}
            if active_filters:
                query = query.filter_by(**active_filters)

        total = query.count()

        if order_by is None:
            order_by = self.model.created_at.desc()

        items = (
            query
            .order_by(order_by)
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )

        logger.debug(
            "Paginated query",
            extra={
                "model":  self.model.__name__,
                "page":   page,
                "limit":  limit,
                "total":  total,
                "returned": len(items),
            },
        )
        return items, total

    # ── Write operations ──────────────────────────────────────────────────────

    def save(self, record: T) -> T:
        """
        Persist a model to the session (INSERT or UPDATE).

        Does NOT commit — caller controls the transaction.

        Args:
            record: Model instance to save.

        Returns:
            The saved model instance (with ID populated after flush).
        """
        db.session.add(record)
        db.session.flush()
        logger.debug(
            "Record saved",
            extra={"model": self.model.__name__, "id": getattr(record, "id", "?")},
        )
        return record

    def delete(self, record: T) -> None:
        """
        Hard-delete a record from the session.

        Prefer soft_delete() for models that use SoftDeleteMixin.

        Args:
            record: Model instance to delete.
        """
        db.session.delete(record)
        logger.debug(
            "Record hard-deleted",
            extra={"model": self.model.__name__, "id": getattr(record, "id", "?")},
        )

    def soft_delete(self, record: T) -> T:
        """
        Soft-delete a record (sets is_deleted=True, deleted_at=now).

        Only valid for models using SoftDeleteMixin.
        Does NOT commit — caller controls the transaction.

        Raises:
            AttributeError: If model does not use SoftDeleteMixin.
        """
        from app.models.mixins import SoftDeleteMixin
        if not isinstance(record, SoftDeleteMixin):
            raise AttributeError(
                f"{self.model.__name__} does not support soft delete. "
                "Add SoftDeleteMixin to the model."
            )
        record.soft_delete()
        db.session.add(record)
        return record

    def commit(self) -> None:
        """Commit the current session transaction."""
        db.session.commit()

    def rollback(self) -> None:
        """Roll back the current session transaction."""
        db.session.rollback()