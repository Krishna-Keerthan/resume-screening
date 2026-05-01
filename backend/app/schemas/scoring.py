"""
app/schemas/scoring.py — Marshmallow input schemas for scoring/matching endpoints.

Changes from Phase 1:
  - Cross-field validators on weight fields.
  - AtsScoreQuerySchema for filtering stored scores.
  - Explicit score range validators (0.0-1.0).
"""

from marshmallow import ValidationError, fields, validate, validates_schema

from app.models.enums import ScoreLabel
from app.schemas.base import BaseSchema

_SCORE_LABELS = [e.value for e in ScoreLabel]


class MatchResumeToJobSchema(BaseSchema):
    """Validates POST /api/v1/scores/match."""
    resume_id    = fields.String(required=True)
    job_id       = fields.String(required=True)
    save_result  = fields.Boolean(load_default=True)
    # If False, compute and return without persisting (useful for live preview)


class RankCandidatesSchema(BaseSchema):
    """Validates POST /api/v1/scores/rank-candidates."""
    job_id      = fields.String(required=True)
    top_n       = fields.Integer(load_default=10, validate=validate.Range(min=1, max=50))
    min_score   = fields.Float(load_default=0.0,  validate=validate.Range(min=0.0, max=1.0))
    stage_filter = fields.String(load_default=None)


class JobRecommendationsSchema(BaseSchema):
    """Validates POST /api/v1/scores/job-recommendations."""
    resume_id = fields.String(required=True)
    top_n     = fields.Integer(load_default=10, validate=validate.Range(min=1, max=50))
    # Filter to only recommend jobs with this status


class SkillGapSchema(BaseSchema):
    """Validates POST /api/v1/scores/skill-gap."""
    resume_id = fields.String(required=True)
    job_id    = fields.String(load_default=None)


class AtsScoreQuerySchema(BaseSchema):
    """Validates GET /api/v1/scores query params — filter stored scores."""
    page       = fields.Integer(load_default=1,  validate=validate.Range(min=1))
    limit      = fields.Integer(load_default=20, validate=validate.Range(min=1, max=100))
    resume_id  = fields.String(load_default=None)
    job_id     = fields.String(load_default=None)
    min_score  = fields.Float(load_default=None,  validate=validate.Range(min=0.0, max=1.0))
    max_score  = fields.Float(load_default=None,  validate=validate.Range(min=0.0, max=1.0))
    score_label = fields.String(load_default=None, validate=validate.OneOf(_SCORE_LABELS))

    @validates_schema
    def validate_score_range(self, data: dict, **kwargs) -> None:
        min_s = data.get("min_score")
        max_s = data.get("max_score")
        if min_s is not None and max_s is not None and min_s > max_s:
            raise ValidationError(
                "min_score cannot be greater than max_score.",
                field_name="min_score",
            )
