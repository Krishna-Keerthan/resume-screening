
"""
app/models/job.py

Job posting model.

Changes from Phase 1:
  - JobStatus and JobType enums replace raw string columns.
  - SoftDeleteMixin — jobs are never hard-deleted (ATS score history preserved).
  - SearchableMixin — title/company ILIKE search helper.
  - Composite indexes for all major query patterns.
  - to_dict_list() for compact paginated responses.

Relationships:
  - recruiter:     many-to-one Recruiter
  - applications:  one-to-many Application (cascade: all, delete-orphan)
"""

from __future__ import annotations


import json
import logging
from typing import Any

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import BaseModel
from app.models.enums import (
    JobStatus, JobType,
    SA_JOB_STATUS, SA_JOB_TYPE,
)
from app.models.mixins import SearchableMixin, SoftDeleteMixin

logger = logging.getLogger(__name__)


class Job( SoftDeleteMixin, SearchableMixin, BaseModel):
    """
    Job posting.

    Soft-deleted when closed — preserves ATS score history.
    Required/nice-to-have skills and responsibilities are stored as
    JSON-serialised lists for SQLite/PostgreSQL portability.
    """

    __tablename__ = "jobs"

    # ── Core content ─────────────────────────────────────────────────────────
    title:       Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    company:     Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text,        nullable=False)

    # JSON-serialised lists
    responsibilities:        Mapped[str | None] = mapped_column(Text, nullable=True)
    required_skills:         Mapped[str | None] = mapped_column(Text, nullable=True)
    nice_to_have_skills:     Mapped[str | None] = mapped_column(Text, nullable=True)
    additional_requirements: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Requirements ─────────────────────────────────────────────────────────
    experience_years: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    location:         Mapped[str]   = mapped_column(String(200), default="Remote", nullable=False)

    # ── Employment type & status ──────────────────────────────────────────────
    job_type: Mapped[str] = mapped_column(
        SA_JOB_TYPE,
        default=JobType.FULL_TIME,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        SA_JOB_STATUS,
        default=JobStatus.ACTIVE,
        nullable=False,
        index=True,
    )

    # ── Compensation ─────────────────────────────────────────────────────────
    salary_min:      Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max:      Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_currency: Mapped[str]        = mapped_column(String(10), default="USD", nullable=False)

    # ── Smart job quality (computed by SmartJobPostingService — Phase 4) ──────
    quality_score:      Mapped[float | None] = mapped_column(Float, nullable=True)
    completeness_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ── Denormalised counter (updated by ApplicationService) ─────────────────
    applicant_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # ── FK ────────────────────────────────────────────────────────────────────
    recruiter_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("recruiters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ── Composite indexes ─────────────────────────────────────────────────────
    __table_args__ = (
        # Active job feed (most common read query)
        Index("ix_jobs_status_created",     "status", "created_at"),
        # Recruiter dashboard — their jobs by status
        Index("ix_jobs_recruiter_status",   "recruiter_id", "status"),
        # Location + status search (job board filter)
        Index("ix_jobs_location_status",    "location", "status"),
        # Experience range filter
        Index("ix_jobs_experience",         "experience_years"),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    recruiter:    Mapped["Recruiter"]    = relationship("Recruiter",    back_populates="jobs")  # noqa: F821
    applications: Mapped[list["Application"]]           = relationship(
        "Application",
        back_populates="job",
        cascade="all, delete-orphan",
        lazy="select",
    )

    # ── JSON property accessors ───────────────────────────────────────────────

    @property
    def required_skills_list(self) -> list[str]:
        return _jlist(self.required_skills)

    @required_skills_list.setter
    def required_skills_list(self, v: list[str]) -> None:
        self.required_skills = json.dumps(v)

    @property
    def nice_to_have_skills_list(self) -> list[str]:
        return _jlist(self.nice_to_have_skills)

    @nice_to_have_skills_list.setter
    def nice_to_have_skills_list(self, v: list[str]) -> None:
        self.nice_to_have_skills = json.dumps(v)

    @property
    def responsibilities_list(self) -> list[str]:
        return _jlist(self.responsibilities)

    @responsibilities_list.setter
    def responsibilities_list(self, v: list[str]) -> None:
        self.responsibilities = json.dumps(v)

    @property
    def additional_requirements_list(self) -> list[str]:
        return _jlist(self.additional_requirements)

    @additional_requirements_list.setter
    def additional_requirements_list(self, v: list[str]) -> None:
        self.additional_requirements = json.dumps(v)

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self, exclude: set[str] | None = None) -> dict[str, Any]:
        """Full record with all list columns expanded."""
        d = super().to_dict(exclude=exclude)
        d["required_skills"]          = self.required_skills_list
        d["nice_to_have_skills"]       = self.nice_to_have_skills_list
        d["responsibilities"]          = self.responsibilities_list
        d["additional_requirements"]   = self.additional_requirements_list
        return d

    def to_dict_list(self) -> dict[str, Any]:
        """Compact view for job board / search results."""
        return {
            "id":              self.id,
            "title":           self.title,
            "company":         self.company,
            "location":        self.location,
            "job_type":        self.job_type,
            "status":          self.status,
            "experience_years": self.experience_years,
            "required_skills": self.required_skills_list,
            "salary_min":      self.salary_min,
            "salary_max":      self.salary_max,
            "salary_currency": self.salary_currency,
            "applicant_count": self.applicant_count,
            "quality_score":   self.quality_score,
            "recruiter_id":    self.recruiter_id,
            "created_at":      self.created_at.isoformat() if self.created_at else None,
        }


def _jlist(value: str | None) -> list:
    """Safely deserialise a JSON text column to a Python list."""
    if not value:
        return []
    try:
        result = json.loads(value)
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, TypeError):
        return []