"""
app/repositories/resume.py

Resume-specific data access methods.

Changes vs previous version:
  - soft_delete() now accepts an optional storage_service argument.
    When provided, it calls storage_service.delete(resume.storage_key)
    before marking is_deleted=True. This keeps storage cleanup co-located
    with the DB record deletion rather than scattering it across routes.
  - All other methods are unchanged.
"""

import logging

from app.core.database import db
from app.models.enums import ParseStatus
from app.models.resume import Resume
from app.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class ResumeRepository(BaseRepository[Resume]):
    """Repository for Resume model."""

    model = Resume

    # ─────────────────────────────────────────────────────────────────────────
    # Queries
    # ─────────────────────────────────────────────────────────────────────────

    def list_by_candidate(
        self,
        candidate_id: str,
        active_only: bool = False,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[Resume], int]:
        """All resumes for a candidate, newest first."""
        query = (
            db.session.query(Resume)
            .filter(
                Resume.candidate_id == candidate_id,
                Resume.is_deleted == False,          # noqa: E712
            )
        )
        if active_only:
            query = query.filter(Resume.is_active == True)  # noqa: E712

        total = query.count()
        items = (
            query
            .order_by(Resume.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )
        return items, total

    def get_active_resume(self, candidate_id: str) -> Resume | None:
        """Get the most recent active parsed resume for a candidate."""
        return (
            db.session.query(Resume)
            .filter(
                Resume.candidate_id == candidate_id,
                Resume.is_active == True,            # noqa: E712
                Resume.is_deleted == False,          # noqa: E712
                Resume.parse_status == ParseStatus.SUCCESS,
            )
            .order_by(Resume.created_at.desc())
            .first()
        )

    def list_pending_parse(self, limit: int = 10) -> list[Resume]:
        """Fetch resumes awaiting parsing — used by background worker."""
        return (
            db.session.query(Resume)
            .filter(
                Resume.parse_status == ParseStatus.PENDING,
                Resume.is_deleted == False,          # noqa: E712
            )
            .order_by(Resume.created_at.asc())       # FIFO
            .limit(limit)
            .all()
        )

    def list_all(
        self,
        page: int = 1,
        limit: int = 20,
        parse_status: str | None = None,
    ) -> tuple[list[Resume], int]:
        """All non-deleted resumes with optional parse_status filter."""
        query = db.session.query(Resume).filter(Resume.is_deleted == False)  # noqa: E712
        if parse_status:
            query = query.filter(Resume.parse_status == parse_status)
        total = query.count()
        items = (
            query
            .order_by(Resume.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
            .all()
        )
        return items, total

    # ─────────────────────────────────────────────────────────────────────────
    # Parse status helpers
    # ─────────────────────────────────────────────────────────────────────────

    def mark_parse_success(self, resume: Resume) -> Resume:
        """Update status to SUCCESS after successful parse."""
        resume.parse_status    = ParseStatus.SUCCESS
        resume.parse_error_msg = None
        db.session.add(resume)
        return resume

    def mark_parse_failed(self, resume: Resume, reason: str) -> Resume:
        """Update status to FAILED with error message."""
        resume.parse_status    = ParseStatus.FAILED
        resume.parse_error_msg = reason[:2000]
        db.session.add(resume)
        return resume

    # ─────────────────────────────────────────────────────────────────────────
    # Active resume management
    # ─────────────────────────────────────────────────────────────────────────

    def deactivate_previous(
        self,
        candidate_id: str,
        exclude_id: str | None = None,
    ) -> None:
        """
        Deactivate all resumes for a candidate except exclude_id.

        Called atomically before setting the new resume active to ensure
        there is never a window where multiple resumes are active.
        """
        query = db.session.query(Resume).filter(
            Resume.candidate_id == candidate_id,
            Resume.is_deleted == False,              # noqa: E712
        )
        if exclude_id:
            query = query.filter(Resume.id != exclude_id)

        query.update(
            {Resume.is_active: False},
            synchronize_session=False,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Soft delete — storage-aware
    # ─────────────────────────────────────────────────────────────────────────

    def soft_delete(self, resume: Resume, storage_service=None) -> None:
        """
        Soft-delete a Resume record.

        If storage_service is provided, the underlying file is deleted from
        storage (Cloudinary or local) before the DB record is marked deleted.
        File deletion is best-effort — a storage failure does NOT abort the
        DB soft-delete.

        Args:
            resume:          Resume ORM instance to delete.
            storage_service: Optional StorageService instance. When None,
                             only the DB record is soft-deleted (no file cleanup).
        """
        # Best-effort storage cleanup
        if storage_service is not None:
            storage_key = getattr(resume, "storage_key", None) or getattr(resume, "file_path", None)
            if storage_key:
                try:
                    storage_service.delete(storage_key)
                except Exception:
                    logger.warning(
                        "Storage delete failed during soft_delete (non-fatal)",
                        extra={"resume_id": resume.id, "storage_key": storage_key},
                        exc_info=True,
                    )

        # Mark as deleted in DB
        resume.is_deleted = True
        resume.is_active  = False
        db.session.add(resume)
        db.session.flush()

        logger.info(
            "Resume soft-deleted",
            extra={
                "resume_id":   resume.id,
                "storage_key": getattr(resume, "storage_key", None),
            },
        )