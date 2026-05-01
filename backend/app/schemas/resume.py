"""
app/schemas/resume.py — Marshmallow schemas for Resume endpoints.
"""

from marshmallow import fields, validate

from app.schemas.base import BaseSchema


class ResumeQuerySchema(BaseSchema):
    """Validates GET /api/v1/resumes query params."""
    page         = fields.Integer(load_default=1,  validate=validate.Range(min=1))
    limit        = fields.Integer(load_default=20, validate=validate.Range(min=1, max=100))
    candidate_id = fields.String(load_default=None)
    parse_status = fields.String(load_default=None, validate=validate.OneOf(["pending", "success", "failed"]))


class AnalyzeResumeSchema(BaseSchema):
    """Validates POST /api/v1/resumes/<id>/analyze body."""
    force_refresh = fields.Boolean(load_default=False)
    # If True, re-run analysis even if cached results exist


class RoleRecommendSchema(BaseSchema):
    """Validates POST /api/v1/resumes/<id>/role-recommendations body."""
    top_n = fields.Integer(load_default=4, validate=validate.Range(min=1, max=10))
