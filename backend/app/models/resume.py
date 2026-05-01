
"""
app/models/resume.py

Resume model — stores the parsed file data for a Candidate.

Changes from Phase 1:
  - ParseStatus enum replaces raw string column.
  - SoftDeleteMixin — resumes are never hard-deleted (score history preserved).
  - Composite indexes for common query patterns.
  - parse_error_msg field — captures failure reason when parse_status=FAILED.
  - to_dict_list() — compact view for resume list endpoint.
  - to_dict_analysis() — analysis-only view for role-suggestion endpoint.

Relationships:
  - candidate:    many-to-one Candidate
  - ats_scores:   one-to-many AtsScore (cascade: all, delete-orphan)
  - applications: one-to-many Application
"""

import json
import logging
from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import BaseModel
from app.models.enums import ParseStatus, SA_PARSE_STATUS
from app.models.mixins import SoftDeleteMixin

logger = logging.getLogger(__name__)


class Resume( SoftDeleteMixin, BaseModel):
    """
    Parsed resume record.

    One candidate can own multiple resume versions.
    The active resume is used for scoring and job matching.
    """

    __tablename__ = "resumes"

    # ── FK ────────────────────────────────────────────────────────────────────
    candidate_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── File metadata ─────────────────────────────────────────────────────────
    filename:     Mapped[str]        = mapped_column(String(500),  nullable=False)
    file_path:    Mapped[str]        = mapped_column(String(1000), nullable=False)
    storage_key:  Mapped[str | None] = mapped_column(          
        String(500), nullable=True,
        comment="Cloudinary public_id (prod) or local file path (dev) — used for deletion"
    )
    file_size_kb: Mapped[int | None] = mapped_column(Integer,      nullable=True)
    file_type:    Mapped[str]        = mapped_column(
        String(10), nullable=False,
        comment="pdf | docx"
    )

    # ── Parsed content (JSON-serialised lists) ────────────────────────────────
    raw_text:       Mapped[str | None] = mapped_column(Text, nullable=True)
    skills:         Mapped[str | None] = mapped_column(JSONB, nullable=True)
    education:      Mapped[str | None] = mapped_column(JSONB, nullable=True)
    experience:     Mapped[str | None] = mapped_column(JSONB, nullable=True)
    certifications: Mapped[str | None] = mapped_column(JSONB, nullable=True)
    projects:       Mapped[str | None] = mapped_column(JSONB, nullable=True)
    summary_text:   Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_info:   Mapped[str | None] = mapped_column(JSONB, nullable=True)
    oov_skills_list:Mapped[str | None] = mapped_column(JSONB, nullable=True)

    # ── Computed metrics ──────────────────────────────────────────────────────
    total_experience_years: Mapped[float] = mapped_column(Float,   default=0.0, nullable=False)
    skill_count:            Mapped[int]   = mapped_column(Integer, default=0,   nullable=False)

    # ── Analysis output (populated by ResumeAnalysisService — Phase 3) ───────
    resume_summary:   Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON dict
    issues_detected:  Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    role_suggestions: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    improvement_tips: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list

    # ── Parse pipeline status ─────────────────────────────────────────────────
    parse_status: Mapped[str] = mapped_column(
        SA_PARSE_STATUS,
        default=ParseStatus.PENDING,
        nullable=False,
    )
    parse_error_msg: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Populated when parse_status=failed"
    )

    # ── Visibility ────────────────────────────────────────────────────────────
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # ── Composite indexes ─────────────────────────────────────────────────────
    __table_args__ = (
        # Pending parse queue — background worker polls this
        Index("ix_resumes_candidate_status", "candidate_id", "parse_status"),
        # Active resumes per candidate
        Index("ix_resumes_candidate_active", "candidate_id", "is_active"),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    candidate:    Mapped["Candidate"] = relationship("Candidate", back_populates="resumes")   # noqa: F821
    ats_scores:   Mapped[list]        = relationship("AtsScore",  back_populates="resume", cascade="all, delete-orphan")
    applications: Mapped[list]        = relationship("Application", back_populates="resume", lazy="select")

    # ── JSON property accessors ───────────────────────────────────────────────

    @property
    def skills_list(self) -> list[str]:
        return _jlist(self.skills)

    @skills_list.setter
    def skills_list(self, v: list) -> None:
        self.skills = json.dumps(v)
        self.skill_count = len(v)

    @property
    def education_list(self) -> list[dict]:
        return _jlist(self.education)

    @education_list.setter
    def education_list(self, v: list) -> None:
        self.education = json.dumps(v)

    @property
    def experience_list(self) -> list[dict]:
        return _jlist(self.experience)

    @experience_list.setter
    def experience_list(self, v: list) -> None:
        self.experience = json.dumps(v)

    @property
    def certifications_list(self) -> list[str]:
        return _jlist(self.certifications)

    @certifications_list.setter
    def certifications_list(self, v: list) -> None:
        self.certifications = json.dumps(v)

    @property
    def projects_list(self) -> list[dict]:
        return _jlist(self.projects)

    @projects_list.setter
    def projects_list(self, v: list) -> None:
        self.projects = json.dumps(v)

    @property
    def oov_skills_list_parsed(self) -> list[str]:
        return _jlist(self.oov_skills_list)

    @oov_skills_list_parsed.setter
    def oov_skills_list_parsed(self, v: list) -> None:
        self.oov_skills_list = json.dumps(v)

    @property
    def issues_list(self) -> list[dict]:
        return _jlist(self.issues_detected)

    @issues_list.setter
    def issues_list(self, v: list) -> None:
        self.issues_detected = json.dumps(v)

    @property
    def role_suggestions_list(self) -> list[dict]:
        return _jlist(self.role_suggestions)

    @role_suggestions_list.setter
    def role_suggestions_list(self, v: list) -> None:
        self.role_suggestions = json.dumps(v)

    @property
    def improvement_tips_list(self) -> list[dict]:
        return _jlist(self.improvement_tips)

    @improvement_tips_list.setter
    def improvement_tips_list(self, v: list) -> None:
        self.improvement_tips = json.dumps(v)

    # Add this property after the existing column definitions:
    @property
    def file_name(self) -> str:
        """Alias for filename — matches frontend type interface."""
        return self.filename or ''
    
    @property
    def file_size_bytes(self) -> int:
        """Convert stored KB to bytes for API consistency."""
        return (self.file_size_kb or 0) * 1024

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self, exclude: set[str] | None = None) -> dict[str, Any]:
        """Full record with all JSON columns expanded."""
        d = super().to_dict(exclude=exclude)
        d["skills"]           = self.skills_list
        d["education"]        = self.education_list
        d["experience"]       = self.experience_list
        d["certifications"]   = self.certifications_list
        d["projects"]         = self.projects_list
        d["issues_detected"]  = self.issues_list
        d["role_suggestions"] = self.role_suggestions_list
        d["improvement_tips"] = self.improvement_tips_list
        return d

    def to_dict_list(self) -> dict[str, Any]:
        """Compact view for paginated list endpoints — omits raw_text."""
        return {
            "id":                     self.id,
            "candidate_id":           self.candidate_id,
            "filename":               self.filename,
            "file_type":              self.file_type,
            "file_size_kb":           self.file_size_kb,
            "parse_status":           self.parse_status,
            "total_experience_years": self.total_experience_years,
            "skill_count":            self.skill_count,
            "is_active":              self.is_active,
            "created_at":             self.created_at.isoformat() if self.created_at else None,
        }

    def to_dict_analysis(self) -> dict[str, Any]:
        """Analysis-only view for role suggestion and issue detection endpoints."""
        return {
            "id":               self.id,
            "candidate_id":     self.candidate_id,
            "skills":           self.skills_list,
            "education":        self.education_list,
            "experience":       self.experience_list,
            "certifications":   self.certifications_list,
            "resume_summary":   self.resume_summary,
            "issues_detected":  self.issues_list,
            "role_suggestions": self.role_suggestions_list,
            "improvement_tips": self.improvement_tips_list,
        }


def _jlist(value: str | None) -> list:
    if not value:
        return []
    try:
        result = json.loads(value)
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, TypeError):
        return []