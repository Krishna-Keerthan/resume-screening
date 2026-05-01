
"""
app/models/ats_score.py

ATS Score — full scoring breakdown for a Resume × Job pair.

Changes from Phase 1:
  - ScoreLabel enum replaces raw string column.
  - UNIQUE constraint on (resume_id, job_id) — one score per pair.
  - Composite indexes for top-candidates-per-job query.
  - score_to_label() utility imported from enums.
  - classmethod from_score_result() — clean construction from scoring dict.

This table is the persistent audit trail for all ML scoring decisions.
The scoring engine writes here; dashboards and explanation endpoints read here.

Relationships:
  - resume:      many-to-one Resume
  - job:         many-to-one Job
  - application: one-to-one Application (optional — standalone scoring supported)
"""

import json
import logging
from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import BaseModel
from app.models.enums import SA_SCORE_LABEL, ScoreLabel, score_to_label

logger = logging.getLogger(__name__)


class AtsScore(BaseModel):
    """
    Full ATS scoring breakdown for a Resume × Job pair.

    One record per (resume, job) pair — updated in-place on re-score.
    Linked to an Application when scored at apply-time.
    """

    __tablename__ = "ats_scores"

    # ── FKs ───────────────────────────────────────────────────────────────────
    resume_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("resumes.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    application_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("applications.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,  # One score per application
    )

    # ── Score components (all in [0.0, 1.0]) ─────────────────────────────────
    semantic_score:        Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    keyword_score:         Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    experience_score:      Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    section_quality_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    final_score:           Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # ── Derived tier label ────────────────────────────────────────────────────
    score_label: Mapped[str] = mapped_column(
        SA_SCORE_LABEL,
        default=ScoreLabel.FAIR,
        nullable=False,
    )

    # ── Semantic availability flag ────────────────────────────────────────────
    semantic_available: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False,
        comment="False when MiniLM encoder was unavailable at score time"
    )

    # ── Explainability payload (JSON lists) ───────────────────────────────────
    matched_skills:   Mapped[str | None] = mapped_column(Text, nullable=True)
    missing_skills:   Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_skills:     Mapped[str | None] = mapped_column(Text, nullable=True)
    improvement_tips: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_text:     Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Weights audit (stored so old scores remain interpretable) ─────────────
    weights_used: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment='JSON dict e.g. {"semantic":0.40,"keyword":0.35,"experience":0.15,"section":0.10}'
    )

    # ── Composite indexes ─────────────────────────────────────────────────────
    __table_args__ = (
        # One score per (resume, job) pair — prevent duplicate scoring
        UniqueConstraint("resume_id", "job_id", name="uq_ats_score_resume_job"),
        # Top-N candidates per job — ORDER BY final_score DESC
        Index("ix_ats_scores_job_score", "job_id", "final_score"),
        # Job recommendations per resume — ORDER BY final_score DESC
        Index("ix_ats_scores_resume_score", "resume_id", "final_score"),
        # Score label filter (e.g. "show only excellent matches")
        Index("ix_ats_scores_label", "score_label"),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    resume:      Mapped["Resume"]           = relationship("Resume",      back_populates="ats_scores")    # noqa: F821
    job:         Mapped["Job"]              = relationship("Job")                                          # noqa: F821
    application: Mapped["Application | None"] = relationship(                                              # noqa: F821
        "Application",
        back_populates="ats_score",
        uselist=False,
    )

    # ── Class-level constructor ───────────────────────────────────────────────

    @classmethod
    def from_score_result(
        cls,
        resume_id: str,
        job_id: str,
        scores: dict[str, float],
        explanation: dict,
        weights: dict[str, float],
        application_id: str | None = None,
        threshold_excellent: float = 0.80,
        threshold_good: float = 0.65,
        threshold_fair: float = 0.50,
    ) -> "AtsScore":
        """
        Construct an AtsScore from a raw scoring result dict.

        Args:
            resume_id:   Resume UUID.
            job_id:      Job UUID.
            scores:      Dict with keys: semantic, keyword, experience, section_quality, final.
            explanation: Dict with keys: matched_skills, missing_skills, extra_skills,
                         improvement_tips, summary.
            weights:     The weight config used for this score.
            application_id: Optional link to an Application.
            threshold_*: Tier boundaries (use app.config values).

        Returns:
            Unsaved AtsScore instance (call .save() + session.commit()).
        """
        final = scores.get("final", 0.0)
        label = score_to_label(final, threshold_excellent, threshold_good, threshold_fair)

        instance = cls(
            resume_id=resume_id,
            job_id=job_id,
            application_id=application_id,
            semantic_score=scores.get("semantic", 0.0),
            keyword_score=scores.get("keyword", 0.0),
            experience_score=scores.get("experience", 0.0),
            section_quality_score=scores.get("section_quality", 0.0),
            final_score=final,
            score_label=label.value,
            semantic_available=scores.get("semantic_available", True),
        )
        instance.matched_skills_list   = explanation.get("matched_skills", [])
        instance.missing_skills_list   = explanation.get("missing_skills", [])
        instance.extra_skills_list     = explanation.get("extra_skills", [])
        instance.improvement_tips_list = explanation.get("improvement_tips", [])
        instance.summary_text          = explanation.get("summary", "")
        instance.weights_used_dict     = weights

        return instance

    # ── JSON property accessors ───────────────────────────────────────────────

    @property
    def matched_skills_list(self) -> list[str]:
        return _jlist(self.matched_skills)

    @matched_skills_list.setter
    def matched_skills_list(self, v: list) -> None:
        self.matched_skills = json.dumps(v)

    @property
    def missing_skills_list(self) -> list[str]:
        return _jlist(self.missing_skills)

    @missing_skills_list.setter
    def missing_skills_list(self, v: list) -> None:
        self.missing_skills = json.dumps(v)

    @property
    def extra_skills_list(self) -> list[str]:
        return _jlist(self.extra_skills)

    @extra_skills_list.setter
    def extra_skills_list(self, v: list) -> None:
        self.extra_skills = json.dumps(v)

    @property
    def improvement_tips_list(self) -> list[dict]:
        return _jlist(self.improvement_tips)

    @improvement_tips_list.setter
    def improvement_tips_list(self, v: list) -> None:
        self.improvement_tips = json.dumps(v)

    @property
    def weights_used_dict(self) -> dict:
        if not self.weights_used:
            return {}
        try:
            return json.loads(self.weights_used)
        except (json.JSONDecodeError, TypeError):
            return {}

    @weights_used_dict.setter
    def weights_used_dict(self, v: dict) -> None:
        self.weights_used = json.dumps(v)

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_dict(self, exclude: set[str] | None = None) -> dict[str, Any]:
        d = super().to_dict(exclude=exclude)
        d["matched_skills"]   = self.matched_skills_list
        d["missing_skills"]   = self.missing_skills_list
        d["extra_skills"]     = self.extra_skills_list
        d["improvement_tips"] = self.improvement_tips_list
        d["weights_used"]     = self.weights_used_dict
        return d

    def to_dict_summary(self) -> dict[str, Any]:
        """Score summary for dashboard cards — no explainability payload."""
        return {
            "id":                    self.id,
            "resume_id":             self.resume_id,
            "job_id":                self.job_id,
            "final_score":           self.final_score,
            "score_label":           self.score_label,
            "semantic_score":        self.semantic_score,
            "keyword_score":         self.keyword_score,
            "experience_score":      self.experience_score,
            "section_quality_score": self.section_quality_score,
            "semantic_available":    self.semantic_available,
        }


def _jlist(value: str | None) -> list:
    if not value:
        return []
    try:
        result = json.loads(value)
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, TypeError):
        return []