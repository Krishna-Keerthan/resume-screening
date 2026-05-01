"""
app/schemas/recruiter.py — Marshmallow schemas for Recruiter endpoints.
"""

from marshmallow import fields, validate

from app.schemas.base import BaseSchema

_COMPANY_SIZES = ("1-10", "11-50", "51-200", "201-500", "500+")


class CreateRecruiterSchema(BaseSchema):
    """Validates POST /api/v1/recruiters body."""
    full_name    = fields.String(required=True, validate=validate.Length(min=1, max=200))
    email        = fields.Email(required=True)
    company_name = fields.String(required=True, validate=validate.Length(min=1, max=300))
    company_size = fields.String(load_default=None, validate=validate.OneOf(_COMPANY_SIZES))
    industry     = fields.String(load_default=None, validate=validate.Length(max=200))
    phone        = fields.String(load_default=None, validate=validate.Length(max=30))
    website_url  = fields.Url(load_default=None, allow_none=True)
    linkedin_url = fields.Url(load_default=None, allow_none=True)


class UpdateRecruiterSchema(BaseSchema):
    """Validates PATCH /api/v1/recruiters/<id> body — all fields optional."""
    full_name    = fields.String(validate=validate.Length(min=1, max=200))
    company_name = fields.String(validate=validate.Length(min=1, max=300))
    company_size = fields.String(validate=validate.OneOf(_COMPANY_SIZES))
    industry     = fields.String(allow_none=True, validate=validate.Length(max=200))
    phone        = fields.String(allow_none=True, validate=validate.Length(max=30))
    website_url  = fields.Url(allow_none=True)
    linkedin_url = fields.Url(allow_none=True)


class RecruiterQuerySchema(BaseSchema):
    """Validates GET /api/v1/recruiters query params."""
    page         = fields.Integer(load_default=1,  validate=validate.Range(min=1))
    limit        = fields.Integer(load_default=20, validate=validate.Range(min=1, max=100))
    search       = fields.String(load_default=None)
    company_name = fields.String(load_default=None)
