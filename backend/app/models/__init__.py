"""
app/models

SQLAlchemy ORM model package.

All model classes are exported here for clean imports throughout the app:

    from app.models import Job, Resume, Candidate       ← preferred
    from app.models.refresh_token import RefreshToken   ← also fine

Import order:
  Enums and mixins first (no FK deps).
  Then models in FK dependency order so SQLAlchemy can resolve relationships.
  (SQLAlchemy handles circular FK refs via string forward references,
   so order doesn't strictly matter — but explicit is better.)

JWT Auth (Phase 7):
  - RefreshToken added to exports.
  - Candidate and Recruiter now have password_hash columns.
"""

# ── Enums (no model dependencies) ────────────────────────────────────────────
from app.models.enums import (  # noqa: F401
    ApplicationStage,
    CompanySize,
    JobStatus,
    JobType,
    ParseStatus,
    ScoreLabel,
    STAGE_TRANSITIONS,
    TERMINAL_STAGES,
    score_to_label,
)

# ── Mixins ────────────────────────────────────────────────────────────────────
from app.models.mixins import SearchableMixin, SoftDeleteMixin  # noqa: F401

# ── ORM Models ────────────────────────────────────────────────────────────────
from app.models.candidate     import Candidate     # noqa: F401
from app.models.recruiter     import Recruiter     # noqa: F401
from app.models.job           import Job           # noqa: F401
from app.models.resume        import Resume        # noqa: F401
from app.models.application   import Application   # noqa: F401
from app.models.ats_score     import AtsScore      # noqa: F401
from app.models.refresh_token import RefreshToken  # noqa: F401  ← Phase 7

__all__ = [
    # Enums
    "ApplicationStage", "CompanySize", "JobStatus", "JobType",
    "ParseStatus", "ScoreLabel", "STAGE_TRANSITIONS", "TERMINAL_STAGES",
    "score_to_label",
    # Mixins
    "SearchableMixin", "SoftDeleteMixin",
    # Models
    "Candidate", "Recruiter", "Job", "Resume", "Application", "AtsScore",
    "RefreshToken", 
]