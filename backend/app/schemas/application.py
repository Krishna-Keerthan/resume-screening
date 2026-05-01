"""
app/schemas/application.py — Marshmallow schemas for Application endpoints.
"""

from marshmallow import fields, validate

from app.schemas.base import BaseSchema
from app.models.application import APPLICATION_STAGES


class CreateApplicationSchema(BaseSchema):
    """Validates POST /api/v1/applications body."""
    candidate_id = fields.String(required=True)
    job_id       = fields.String(required=True)
    resume_id    = fields.String(required=True)
    cover_letter = fields.String(load_default=None, validate=validate.Length(max=5000))


class UpdateApplicationStageSchema(BaseSchema):
    """Validates PATCH /api/v1/applications/<id>/stage body."""
    stage            = fields.String(required=True, validate=validate.OneOf(APPLICATION_STAGES))
    recruiter_notes  = fields.String(load_default=None, validate=validate.Length(max=2000))
    rejection_reason = fields.String(load_default=None, validate=validate.Length(max=1000))


class ApplicationQuerySchema(BaseSchema):
    """Validates GET /api/v1/applications query params."""
    page         = fields.Integer(load_default=1,  validate=validate.Range(min=1))
    limit        = fields.Integer(load_default=20, validate=validate.Range(min=1, max=100))
    job_id       = fields.String(load_default=None)
    candidate_id = fields.String(load_default=None)
    stage        = fields.String(load_default=None, validate=validate.OneOf(APPLICATION_STAGES))
