"""
app/schemas/response/job.py — Job response serialisation schemas.
"""

from marshmallow import fields

from app.schemas.base import BaseSchema


class JobResponseSchema(BaseSchema):
    """Full job record — used for GET /jobs/<id>."""

    id          = fields.String()
    title       = fields.String()
    company     = fields.String()
    description = fields.String()

    responsibilities        = fields.List(fields.String(), dump_default=[])
    required_skills         = fields.List(fields.String(), dump_default=[])
    nice_to_have_skills     = fields.List(fields.String(), dump_default=[])
    additional_requirements = fields.List(fields.String(), dump_default=[])

    experience_years = fields.Float()
    location         = fields.String()
    job_type         = fields.String()
    status           = fields.String()

    salary_min      = fields.Integer(dump_default=None)
    salary_max      = fields.Integer(dump_default=None)
    salary_currency = fields.String()

    quality_score      = fields.Float(dump_default=None)
    completeness_score = fields.Float(dump_default=None)
    applicant_count    = fields.Integer()
    recruiter_id       = fields.String(dump_default=None)

    created_at = fields.String()
    updated_at = fields.String()


class JobListSchema(BaseSchema):
    """Compact job card — used in job board / search results."""

    id               = fields.String()
    title            = fields.String()
    company          = fields.String()
    location         = fields.String()
    job_type         = fields.String()
    status           = fields.String()
    experience_years = fields.Float()
    required_skills  = fields.List(fields.String(), dump_default=[])
    salary_min       = fields.Integer(dump_default=None)
    salary_max       = fields.Integer(dump_default=None)
    salary_currency  = fields.String()
    applicant_count  = fields.Integer()
    quality_score    = fields.Float(dump_default=None)
    recruiter_id     = fields.String(dump_default=None)
    created_at       = fields.String()
