
"""
app/models/application.py

Application model — links a Candidate to a Job via a specific Resume version.

Changes from Phase 1:
  - ApplicationStage enum replaces APPLICATION_STAGES tuple.
  - UNIQUE constraint on (candidate_id, job_id) — one application per job.
  - Composite indexes for all recruiter dashboard query patterns.
  - stage_history (JSON) — immutable audit log of all stage transitions.
  - to_dict_list() — compact recruiter table view.

APPLICATION_STAGES tuple is kept for Marshmallow schema backward compatibility.
The enum is the authoritative source; the tuple is derived from it.

Relationships:
  - candidate: many-to-one Candidate
  - job:       many-to-one Job
  - resume:    many-to-one Resume (version submitted with this application)
  - ats_score: one-to-one AtsScore
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import BaseModel
from app.models.enums import (
    ApplicationStage,
    SA_APPLICATION_STAGE,
    TERMINAL_STAGES,
    STAGE_TRANSITIONS,
)

logger = logging.getLogger(__name__)

# Keep the tuple for Marshmallow schema imports (backward compatible)
APPLICATION_STAGES = tuple(s.value for s in ApplicationStage)


class Application(BaseModel):
    """
    Candidate application to a job posting.

    One candidate can apply to the same job only once (enforced by UNIQUE
    constraint). The application tracks stage transitions and preserves a
    JSON audit log of all changes.
    """

    __tablename__ = "applications"

    # ── FKs ───────────────────────────────────────────────────────────────────
    candidate_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    resume_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("resumes.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    stage: Mapped[str] = mapped_column(
        SA_APPLICATION_STAGE,
        default=ApplicationStage.APPLIED,
        nullable=False,
        index=True,
    )

    # JSON audit log: [{"stage": "reviewed", "at": "2024-01-01T12:00:00Z", "by": "recruiter_id"}, ...]
    stage_history: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="JSON list — immutable audit trail of stage transitions"
    )

    # ── Recruiter notes ───────────────────────────────────────────────────────
    recruiter_notes:  Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Candidate content ─────────────────────────────────────────────────────
    cover_letter: Mapped[str | None] = mapped_column(Text, nullable=True)

    improvement_plan: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="AI-generated improvement plan for low-scoring applications"
    )

    # ── Composite indexes + UNIQUE constraint ─────────────────────────────────
    __table_args__ = (
        # Prevent duplicate applications — one candidate per job
        UniqueConstraint("candidate_id", "job_id", name="uq_application_candidate_job"),
        # Recruiter dashboard: filter job applicants by stage
        Index("ix_applications_job_stage",      "job_id",       "stage"),
        # Candidate: view all their applications by stage
        Index("ix_applications_candidate_stage","candidate_id", "stage"),
        # Date-ordered applicant list per job
        Index("ix_applications_job_created",    "job_id",       "created_at"),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    candidate: Mapped["Candidate"]       = relationship("Candidate", back_populates="applications")  # noqa: F821
    job:       Mapped["Job"]             = relationship("Job",       back_populates="applications")  # noqa: F821
    resume:    Mapped["Resume"]          = relationship("Resume",    back_populates="applications")  # noqa: F821
    ats_score: Mapped["AtsScore | None"] = relationship(             # noqa: F821
        "AtsScore",
        back_populates="application",
        uselist=False,
    )

    # ── Stage management ──────────────────────────────────────────────────────

    @property
    def stage_history_list(self) -> list[dict]:
        """Deserialised stage transition history."""
        if not self.stage_history:
            return []
        try:
            result = json.loads(self.stage_history)
            return result if isinstance(result, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    def advance_stage(self, new_stage: str, actor_id: str | None = None) -> None:
        """
        Transition to a new stage and append to audit history.

        Args:
            new_stage: Target stage value (must be a valid ApplicationStage).
            actor_id:  ID of the actor making the change (recruiter ID etc.).

        Raises:
            ValueError: If transition is not allowed from the current stage.
        """
        current = ApplicationStage(self.stage)
        target  = ApplicationStage(new_stage)

        from app.models.enums import STAGE_TRANSITIONS
        allowed = STAGE_TRANSITIONS.get(current, frozenset())

        if target not in allowed:
            raise ValueError(
                f"Invalid stage transition: {current.value!r} → {target.value!r}. "
                f"Allowed: {[s.value for s in allowed] or 'none (terminal stage)'}."
            )

        # Append to history before changing stage
        history = self.stage_history_list
        history.append({
            "from":  self.stage,
            "to":    target.value,
            "at":    datetime.now(timezone.utc).isoformat(),
            "by":    actor_id,
        })
        self.stage_history = json.dumps(history)
        self.stage = target.value

        logger.info(
            "Application stage advanced",
            extra={"application_id": self.id, "from": current.value, "to": target.value},
        )


    @property
    def applied_at(self):
        """Alias for created_at — the moment the application was submitted."""
        return self.created_at

    @property
    def is_terminal(self) -> bool:
        """True when the application is in a terminal stage (no further transitions)."""
        try:
            return ApplicationStage(self.stage) in TERMINAL_STAGES
        except ValueError:
            return False

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self, exclude: set[str] | None = None) -> dict[str, Any]:
        d = super().to_dict(exclude=exclude)
        d["stage_history"] = self.stage_history_list
        d["is_terminal"]   = self.is_terminal
        return d

    def to_dict_list(self) -> dict[str, Any]:
        """Compact view for recruiter applicant table."""
        return {
            "id":           self.id,
            "candidate_id": self.candidate_id,
            "job_id":       self.job_id,
            "resume_id":    self.resume_id,
            "stage":        self.stage,
            "is_terminal":  self.is_terminal,
            "created_at":   self.created_at.isoformat() if self.created_at else None,
        }