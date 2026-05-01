"""
app/schemas/candidate.py — Marshmallow schemas for Candidate endpoints.
"""

from marshmallow import fields, validate

from app.schemas.base import BaseSchema


class CreateCandidateSchema(BaseSchema):
    """Validates POST /api/v1/candidates body."""
    full_name  = fields.String(required=True, validate=validate.Length(min=1, max=200))
    email      = fields.Email(required=True)
    phone      = fields.String(load_default=None, validate=validate.Length(max=30))
    location   = fields.String(load_default=None, validate=validate.Length(max=200))
    headline   = fields.String(load_default=None, validate=validate.Length(max=300))

    linkedin_url   = fields.Url(load_default=None, allow_none=True)
    github_url     = fields.Url(load_default=None, allow_none=True)
    portfolio_url  = fields.Url(load_default=None, allow_none=True)

    preferred_roles     = fields.List(fields.String(), load_default=[])
    preferred_locations = fields.List(fields.String(), load_default=[])
    open_to_work        = fields.Boolean(load_default=True)


class UpdateCandidateSchema(BaseSchema):
    """Validates PATCH /api/v1/candidates/<id> body — all fields optional."""
    full_name  = fields.String(validate=validate.Length(min=1, max=200))
    phone      = fields.String(allow_none=True, validate=validate.Length(max=30))
    location   = fields.String(allow_none=True, validate=validate.Length(max=200))
    headline   = fields.String(allow_none=True, validate=validate.Length(max=300))

    linkedin_url   = fields.Url(allow_none=True)
    github_url     = fields.Url(allow_none=True)
    portfolio_url  = fields.Url(allow_none=True)

    preferred_roles     = fields.List(fields.String())
    preferred_locations = fields.List(fields.String())
    open_to_work        = fields.Boolean()


class CandidateQuerySchema(BaseSchema):
    """Validates GET /api/v1/candidates query params."""
    page          = fields.Integer(load_default=1, validate=validate.Range(min=1))
    limit         = fields.Integer(load_default=20, validate=validate.Range(min=1, max=100))
    search        = fields.String(load_default=None)
    open_to_work  = fields.Boolean(load_default=None)
    location      = fields.String(load_default=None)
