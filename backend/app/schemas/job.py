"""
app/schemas/job.py — Marshmallow input validation schemas for Job endpoints.

Changes from Phase 1:
  - JobStatus and JobType enum values used in OneOf validators.
  - Cross-field validator: salary_min <= salary_max.
  - SmartJobAssistSchema expanded.
  - JobSearchSchema for hybrid BM25+semantic search endpoint.
"""

from marshmallow import ValidationError, fields, post_load, validate, validates_schema

from app.models.enums import JobStatus, JobType
from app.schemas.base import BaseSchema

# Derive valid values from enums — single source of truth
_JOB_TYPES    = [e.value for e in JobType]
_JOB_STATUSES = [e.value for e in JobStatus]


class CreateJobSchema(BaseSchema):
    """Validates POST /api/v1/jobs body."""

    title          = fields.String(required=True, validate=validate.Length(min=2, max=300))
    company        = fields.String(required=True, validate=validate.Length(min=1, max=300))
    description    = fields.String(required=True, validate=validate.Length(min=20))

    responsibilities        = fields.List(fields.String(), load_default=[])
    required_skills         = fields.List(fields.String(), load_default=[])
    nice_to_have_skills     = fields.List(fields.String(), load_default=[])
    additional_requirements = fields.List(fields.String(), load_default=[])

    experience_years = fields.Float(load_default=0.0, validate=validate.Range(min=0, max=50))
    location         = fields.String(load_default="Remote", validate=validate.Length(max=200))
    job_type         = fields.String(load_default=JobType.FULL_TIME.value, validate=validate.OneOf(_JOB_TYPES))
    status           = fields.String(load_default=JobStatus.ACTIVE.value,  validate=validate.OneOf(_JOB_STATUSES))

    salary_min      = fields.Integer(load_default=None, allow_none=True, validate=validate.Range(min=0))
    salary_max      = fields.Integer(load_default=None, allow_none=True, validate=validate.Range(min=0))
    salary_currency = fields.String(load_default="USD", validate=validate.Length(max=10))

    recruiter_id = fields.String(load_default=None)

    @validates_schema
    def validate_salary_range(self, data: dict, **kwargs) -> None:
        """salary_min must be <= salary_max when both are provided."""
        s_min = data.get("salary_min")
        s_max = data.get("salary_max")
        if s_min is not None and s_max is not None and s_min > s_max:
            raise ValidationError(
                f"salary_min ({s_min}) cannot be greater than salary_max ({s_max}).",
                field_name="salary_min",
            )


class UpdateJobSchema(BaseSchema):
    """Validates PATCH /api/v1/jobs/<id> body — all fields optional."""

    title                   = fields.String(validate=validate.Length(min=2, max=300))
    company                 = fields.String(validate=validate.Length(min=1, max=300))
    description             = fields.String(validate=validate.Length(min=20))
    responsibilities        = fields.List(fields.String())
    required_skills         = fields.List(fields.String())
    nice_to_have_skills     = fields.List(fields.String())
    additional_requirements = fields.List(fields.String())
    experience_years        = fields.Float(validate=validate.Range(min=0, max=50))
    location                = fields.String(validate=validate.Length(max=200))
    job_type                = fields.String(validate=validate.OneOf(_JOB_TYPES))
    status                  = fields.String(validate=validate.OneOf(_JOB_STATUSES))
    salary_min              = fields.Integer(allow_none=True, validate=validate.Range(min=0))
    salary_max              = fields.Integer(allow_none=True, validate=validate.Range(min=0))
    salary_currency         = fields.String(validate=validate.Length(max=10))

    @validates_schema
    def validate_salary_range(self, data: dict, **kwargs) -> None:
        s_min = data.get("salary_min")
        s_max = data.get("salary_max")
        if s_min is not None and s_max is not None and s_min > s_max:
            raise ValidationError(
                f"salary_min ({s_min}) cannot be greater than salary_max ({s_max}).",
                field_name="salary_min",
            )


class JobQuerySchema(BaseSchema):
    """Validates GET /api/v1/jobs query params."""

    page           = fields.Integer(load_default=1,  validate=validate.Range(min=1))
    limit          = fields.Integer(load_default=20, validate=validate.Range(min=1, max=100))
    search         = fields.String(load_default=None)
    status         = fields.String(load_default=None, validate=validate.OneOf(_JOB_STATUSES))
    job_type       = fields.String(load_default=None, validate=validate.OneOf(_JOB_TYPES))
    location       = fields.String(load_default=None)
    recruiter_id   = fields.String(load_default=None)
    min_experience = fields.Float(load_default=None, validate=validate.Range(min=0))
    max_experience = fields.Float(load_default=None, validate=validate.Range(min=0))

    @validates_schema
    def validate_experience_range(self, data: dict, **kwargs) -> None:
        min_exp = data.get("min_experience")
        max_exp = data.get("max_experience")
        if min_exp is not None and max_exp is not None and min_exp > max_exp:
            raise ValidationError(
                "min_experience cannot be greater than max_experience.",
                field_name="min_experience",
            )


class SmartJobAssistSchema(BaseSchema):
    """
    Validates POST /api/v1/jobs/assist — Groq-powered smart job creation.

    The Groq service will:
      1. Extract structured skill list from description.
      2. Suggest quality improvements.
      3. Check for duplicate postings.
      4. Return quality + completeness scores.
    """
    description = fields.String(required=True, validate=validate.Length(min=20, max=10000))
    title       = fields.String(load_default=None, validate=validate.Length(max=300))
    recruiter_id = fields.String(load_default=None)


class JobSearchSchema(BaseSchema):
    """
    Validates POST /api/v1/jobs/search — hybrid BM25 + semantic search.

    The search service combines lexical (BM25) and semantic (MiniLM)
    similarity for optimal job discovery.
    """
    query          = fields.String(required=True, validate=validate.Length(min=1, max=500))
    top_n          = fields.Integer(load_default=20, validate=validate.Range(min=1, max=100))
    status         = fields.String(load_default=JobStatus.ACTIVE.value, validate=validate.OneOf(_JOB_STATUSES))
    location       = fields.String(load_default=None)
    job_type       = fields.String(load_default=None, validate=validate.OneOf(_JOB_TYPES))
    min_experience = fields.Float(load_default=None, validate=validate.Range(min=0))
    max_experience = fields.Float(load_default=None, validate=validate.Range(min=0))
    # Weight split between BM25 and semantic (must sum to 1.0)
    bm25_weight    = fields.Float(load_default=0.4,  validate=validate.Range(min=0.0, max=1.0))
    semantic_weight = fields.Float(load_default=0.6, validate=validate.Range(min=0.0, max=1.0))

    @validates_schema
    def validate_weights(self, data: dict, **kwargs) -> None:
        bm25 = data.get("bm25_weight", 0.4)
        sem  = data.get("semantic_weight", 0.6)
        if not (0.99 <= bm25 + sem <= 1.01):
            raise ValidationError(
                f"bm25_weight + semantic_weight must sum to 1.0, got {bm25 + sem:.2f}.",
                field_name="bm25_weight",
            )
