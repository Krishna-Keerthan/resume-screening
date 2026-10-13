"""
app/schemas/scoring.py — Marshmallow input schemas for scoring/matching endpoints.
"""

from marshmallow import fields, validate

from app.schemas.base import BaseSchema


class MatchResumeToJobSchema(BaseSchema):
    """Validates POST /api/v1/scores/match."""
    resume_id    = fields.String(required=True)
    job_id       = fields.String(required=True)
    save_result  = fields.Boolean(load_default=True)
    # If False, compute and return without persisting (useful for live preview)


class JobRecommendationsSchema(BaseSchema):
    """Validates POST /api/v1/scores/job-recommendations."""
    resume_id = fields.String(required=True)
    top_n     = fields.Integer(load_default=10, validate=validate.Range(min=1, max=50))
