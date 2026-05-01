"""
app/models/candidate.py

Candidate profile model.

FIXES APPLIED:
  MD-01 — MRO (Method Resolution Order) inversion.

    Original:  class Candidate(BaseModel, SoftDeleteMixin)
    Problem:   Python's C3 linearisation resolves to_dict() from BaseModel
               first. SoftDeleteMixin.to_dict() calls super().to_dict(), which
               is also BaseModel.to_dict() when Candidate appears first.
               Result: the MRO chain was correct by accident here, but the
               pattern is fragile and breaks when a third mixin is added.

    Fixed:     class Candidate(SoftDeleteMixin, BaseModel)
               MRO: Candidate → SoftDeleteMixin → BaseModel → ...
               SoftDeleteMixin.to_dict() runs first, enriches the dict with
               soft-delete fields, then calls super() to reach BaseModel.
               This is the intended pattern for cooperative multiple inheritance.

JWT Auth changes (Phase 7):
  - password_hash: scrypt-hashed password stored by /auth/register/candidate.
    Nullable so existing rows migrate safely — old accounts simply cannot log
    in until a password is set.

All other fields, indexes, and relationships are unchanged from Phase 2.

Relationships:
  - resumes:      one-to-many Resume     (cascade: all, delete-orphan)
  - applications: one-to-many Application (cascade: all, delete-orphan)
"""

import json
from typing import Any

from sqlalchemy import Boolean, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import BaseModel, db

# FIX MD-01: import order matters; SoftDeleteMixin must come before BaseModel in MRO
from app.models.mixins import SoftDeleteMixin


# FIX MD-01: was (BaseModel, SoftDeleteMixin) — now (SoftDeleteMixin, BaseModel)
# MRO is now: Candidate → SoftDeleteMixin → BaseModel → db.Model → ...
# SoftDeleteMixin.to_dict() enriches the dict, then delegates to BaseModel.to_dict()
# via super(). With the old order, to_dict() resolved to BaseModel first and
# SoftDeleteMixin's fields were appended inconsistently.
class Candidate(SoftDeleteMixin, BaseModel):
    """
    Job-seeker profile.

    Candidates upload resumes, receive role suggestions and job recommendations,
    and track their application lifecycle.
    """

    __tablename__ = "candidates"

    # ── Identity ──────────────────────────────────────────────────────────────
    full_name: Mapped[str] = mapped_column(
        String(200), nullable=False
    )
    email: Mapped[str] = mapped_column(
        String(254), unique=True, nullable=False, index=True
    )
    phone:    Mapped[str | None] = mapped_column(String(30),  nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    headline: Mapped[str | None] = mapped_column(
        String(300), nullable=True,
        comment="e.g. 'Senior Python Developer | 5yrs exp | Open to remote'"
    )

    # ── Auth ──────────────────────────────────────────────────────────────────
    # scrypt hash from Werkzeug — NEVER store plain text here.
    # Nullable so rows created before Phase 7 migrate without error.
    password_hash: Mapped[str | None] = mapped_column(
        String(256),
        nullable=True,
        comment="Werkzeug scrypt hash. NULL = account predates JWT auth.",
    )

    # ── Social profiles ───────────────────────────────────────────────────────
    linkedin_url:  Mapped[str | None] = mapped_column(String(500), nullable=True)
    github_url:    Mapped[str | None] = mapped_column(String(500), nullable=True)
    portfolio_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # ── Preferences (JSON-serialised lists) ───────────────────────────────────
    preferred_roles: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment='JSON list e.g. ["Backend Engineer","ML Engineer"]'
    )
    preferred_locations: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment='JSON list e.g. ["Remote","Chennai"]'
    )

    # ── Status flags ──────────────────────────────────────────────────────────
    open_to_work: Mapped[bool] = mapped_column(Boolean, default=True,  nullable=False)
    is_active:    Mapped[bool] = mapped_column(Boolean, default=True,  nullable=False)

    # ── Composite indexes ─────────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_candidates_open_active", "open_to_work", "is_active"),
        Index("ix_candidates_location",    "location"),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    resumes: Mapped[list] = relationship(
        "Resume",
        back_populates="candidate",
        cascade="all, delete-orphan",
        lazy="select",
        order_by="Resume.created_at.desc()",
    )
    applications: Mapped[list] = relationship(
        "Application",
        back_populates="candidate",
        cascade="all, delete-orphan",
        lazy="select",
    )

    # ── JSON property accessors ───────────────────────────────────────────────

    @property
    def preferred_roles_list(self) -> list[str]:
        return _safe_json_list(self.preferred_roles)

    @preferred_roles_list.setter
    def preferred_roles_list(self, value: list[str]) -> None:
        self.preferred_roles = json.dumps(value)

    @property
    def preferred_locations_list(self) -> list[str]:
        return _safe_json_list(self.preferred_locations)

    @preferred_locations_list.setter
    def preferred_locations_list(self, value: list[str]) -> None:
        self.preferred_locations = json.dumps(value)

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self, exclude: set[str] | None = None) -> dict[str, Any]:
        """Full record — expands JSON list columns. Never includes password_hash."""
        _exclude = (exclude or set()) | {"password_hash"}
        d = super().to_dict(exclude=_exclude)
        d["preferred_roles"]     = self.preferred_roles_list
        d["preferred_locations"] = self.preferred_locations_list
        return d

    def to_dict_list(self) -> dict[str, Any]:
        """Compact representation for paginated list endpoints."""
        return {
            "id":           self.id,
            "full_name":    self.full_name,
            "email":        self.email,
            "location":     self.location,
            "headline":     self.headline,
            "open_to_work": self.open_to_work,
            "created_at":   self.created_at.isoformat() if self.created_at else None,
        }

    def to_dict_public(self) -> dict[str, Any]:
        """External-safe view — omits internal flags and auth fields."""
        return self.to_dict(exclude={"is_active"})


def _safe_json_list(value: str | None) -> list:
    if not value:
        return []
    try:
        result = json.loads(value)
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, TypeError):
        return []