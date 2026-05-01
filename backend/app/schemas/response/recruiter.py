"""
app/schemas/response/recruiter.py — Recruiter response serialisation schemas.
"""

from marshmallow import fields

from app.schemas.base import BaseSchema


class RecruiterResponseSchema(BaseSchema):
    """Full recruiter record — used for GET /recruiters/<id>."""

    id           = fields.String()
    full_name    = fields.String()
    email        = fields.Email()
    company_name = fields.String()
    company_size = fields.String(dump_default=None)
    industry     = fields.String(dump_default=None)
    phone        = fields.String(dump_default=None)
    website_url  = fields.String(dump_default=None)
    linkedin_url = fields.String(dump_default=None)

    total_jobs_posted = fields.Integer(dump_default=0)
    total_hires       = fields.Integer(dump_default=0)
    platform_rank     = fields.Integer(dump_default=0)

    created_at = fields.String()
    updated_at = fields.String()

    # Computed by service
    active_jobs_count = fields.Integer(dump_default=0)


class RecruiterListSchema(BaseSchema):
    """Compact recruiter record for list endpoints."""

    id           = fields.String()
    full_name    = fields.String()
    company_name = fields.String()
    company_size = fields.String(dump_default=None)
    industry     = fields.String(dump_default=None)
    total_jobs_posted = fields.Integer()
    platform_rank     = fields.Integer()
    created_at        = fields.String()
