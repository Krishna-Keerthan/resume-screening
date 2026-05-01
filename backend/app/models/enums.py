
"""
app/models/enums.py

Domain enum classes for the ATS platform.

Design decisions:
  - All enums inherit from (str, Enum) so values serialize naturally to JSON
    strings and work transparently in SQLAlchemy string columns without an
    adapter. "stage == 'applied'" and "stage == ApplicationStage.APPLIED"
    both evaluate correctly.

  - SAEnum (SQLAlchemy Enum type) is provided as a pre-built column type
    for each enum. Using SAEnum instead of String for enum columns gives us:
      * PostgreSQL ENUM type (faster, validates at DB level, indexed efficiently)
      * SQLite falls back to VARCHAR automatically
      * Alembic tracks enum type changes in migrations

  - Enums are imported by models — models are NOT imported by enums.
    This keeps the dependency arrow pointing one way: models → enums.

Usage:
    # In a model:
    from app.models.enums import ApplicationStage, SA_APPLICATION_STAGE
    stage: Mapped[str] = mapped_column(SA_APPLICATION_STAGE, default=ApplicationStage.APPLIED)

    # In a service / query:
    from app.models.enums import ApplicationStage
    .filter(Application.stage == ApplicationStage.SHORTLISTED)

    # In a Marshmallow schema:
    from app.models.enums import ApplicationStage
    stage = fields.String(validate=validate.OneOf([e.value for e in ApplicationStage]))
"""

from enum import Enum

from sqlalchemy import Enum as SAEnum

# ─────────────────────────────────────────────────────────────────────────────
# Application lifecycle
# ─────────────────────────────────────────────────────────────────────────────

class ApplicationStage(str, Enum):
    """
    Candidate application lifecycle stages.

    Flow:  APPLIED → REVIEWED → SHORTLISTED → INTERVIEWING → OFFERED → HIRED
                                                           └──────────────→ REJECTED
           Any stage → WITHDRAWN (candidate withdraws)
    """
    APPLIED       = "applied"
    REVIEWED      = "reviewed"
    SHORTLISTED   = "shortlisted"
    INTERVIEWING  = "interviewing"
    OFFERED       = "offered"
    HIRED         = "hired"
    REJECTED      = "rejected"
    WITHDRAWN     = "withdrawn"


# Terminal stages — application cannot advance further
TERMINAL_STAGES = frozenset({
    ApplicationStage.HIRED,
    ApplicationStage.REJECTED,
    ApplicationStage.WITHDRAWN,
})

# Valid forward transitions: stage → set of allowed next stages
STAGE_TRANSITIONS: dict[ApplicationStage, frozenset] = {
    ApplicationStage.APPLIED:      frozenset({
        ApplicationStage.REVIEWED,
        ApplicationStage.SHORTLISTED,   # ← add
        ApplicationStage.INTERVIEWING,  # ← add (power-user skip)
        ApplicationStage.REJECTED,
        ApplicationStage.WITHDRAWN,
    }),
    ApplicationStage.REVIEWED:     frozenset({
        ApplicationStage.SHORTLISTED,
        ApplicationStage.INTERVIEWING,  # ← add
        ApplicationStage.REJECTED,
        ApplicationStage.WITHDRAWN,
    }),
    ApplicationStage.SHORTLISTED:  frozenset({
        ApplicationStage.INTERVIEWING,
        ApplicationStage.REJECTED,
        ApplicationStage.WITHDRAWN,
    }),
    ApplicationStage.INTERVIEWING: frozenset({
        ApplicationStage.OFFERED,
        ApplicationStage.REJECTED,
        ApplicationStage.WITHDRAWN,
    }),
    ApplicationStage.OFFERED:      frozenset({
        ApplicationStage.HIRED,
        ApplicationStage.REJECTED,
        ApplicationStage.WITHDRAWN,
    }),
    ApplicationStage.HIRED:        frozenset(),
    ApplicationStage.REJECTED:     frozenset(),
    ApplicationStage.WITHDRAWN:    frozenset(),
}


# ─────────────────────────────────────────────────────────────────────────────
# Job status
# ─────────────────────────────────────────────────────────────────────────────

class JobStatus(str, Enum):
    """
    Publication status of a job posting.

    DRAFT:   Created but not visible to candidates.
    ACTIVE:  Visible and accepting applications.
    PAUSED:  Temporarily hidden (not deleted).
    CLOSED:  No longer accepting applications (filled or cancelled).
    """
    DRAFT  = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    CLOSED = "closed"


# ─────────────────────────────────────────────────────────────────────────────
# Job employment type
# ─────────────────────────────────────────────────────────────────────────────

class JobType(str, Enum):
    """Employment type for a job posting."""
    FULL_TIME  = "full-time"
    PART_TIME  = "part-time"
    CONTRACT   = "contract"
    INTERNSHIP = "internship"
    FREELANCE  = "freelance"


# ─────────────────────────────────────────────────────────────────────────────
# Resume parse status
# ─────────────────────────────────────────────────────────────────────────────

class ParseStatus(str, Enum):
    """
    State of the resume parsing pipeline for a given file.

    PENDING: File uploaded, not yet processed.
    SUCCESS: Parsed successfully — skills/experience populated.
    FAILED:  Parsing error — see parse_error_msg on the Resume record.
    """
    PENDING = "pending"
    SUCCESS = "success"
    FAILED  = "failed"


# ─────────────────────────────────────────────────────────────────────────────
# ATS score label
# ─────────────────────────────────────────────────────────────────────────────

class ScoreLabel(str, Enum):
    """
    Human-readable tier label derived from a final ATS score.

    Thresholds (configurable in BaseConfig):
      EXCELLENT: >= 0.80
      GOOD:      >= 0.65
      FAIR:      >= 0.50
      WEAK:      <  0.50
    """
    EXCELLENT = "excellent"
    GOOD      = "good"
    FAIR      = "fair"
    WEAK      = "weak"


# ─────────────────────────────────────────────────────────────────────────────
# Company size bands
# ─────────────────────────────────────────────────────────────────────────────

class CompanySize(str, Enum):
    """Headcount band for recruiter company size."""
    MICRO  = "1-10"
    SMALL  = "11-50"
    MEDIUM = "51-200"
    LARGE  = "201-500"
    XLARGE = "500+"


# ─────────────────────────────────────────────────────────────────────────────
# SQLAlchemy Enum column types
# Pre-built to avoid repeating create_constraint=False everywhere.
# create_constraint=False → SQLite compatible (falls back to VARCHAR).
# native_enum=False       → stores string values, not integers.
# ─────────────────────────────────────────────────────────────────────────────

def _sa_enum(enum_class: type, name: str) -> SAEnum:
    """
    Build a SQLAlchemy Enum column type from a Python Enum.

    Args:
        enum_class: The Enum class.
        name:       The PostgreSQL type name (used in migrations).

    Returns:
        SAEnum instance ready to use as a column type.
    """
    return SAEnum(
        enum_class,
        name=name,
        create_constraint=False,   # No CHECK constraint — validated at app layer
        native_enum=False,         # Store as VARCHAR — SQLite compatible
        values_callable=lambda obj: [e.value for e in obj],
    )


SA_APPLICATION_STAGE = _sa_enum(ApplicationStage, "application_stage")
SA_JOB_STATUS        = _sa_enum(JobStatus,        "job_status")
SA_JOB_TYPE          = _sa_enum(JobType,          "job_type")
SA_PARSE_STATUS      = _sa_enum(ParseStatus,      "parse_status")
SA_SCORE_LABEL       = _sa_enum(ScoreLabel,       "score_label")
SA_COMPANY_SIZE      = _sa_enum(CompanySize,      "company_size")


# ─────────────────────────────────────────────────────────────────────────────
# Helper: derive ScoreLabel from a numeric score
# ─────────────────────────────────────────────────────────────────────────────

def score_to_label(
    score: float,
    threshold_excellent: float = 0.80,
    threshold_good: float = 0.65,
    threshold_fair: float = 0.50,
) -> ScoreLabel:
    """
    Convert a numeric ATS score (0.0–1.0) to a ScoreLabel tier.

    Args:
        score:               Final weighted ATS score.
        threshold_excellent: Min score for EXCELLENT tier.
        threshold_good:      Min score for GOOD tier.
        threshold_fair:      Min score for FAIR tier.

    Returns:
        ScoreLabel enum value.
    """
    if score >= threshold_excellent:
        return ScoreLabel.EXCELLENT
    if score >= threshold_good:
        return ScoreLabel.GOOD
    if score >= threshold_fair:
        return ScoreLabel.FAIR
    return ScoreLabel.WEAK