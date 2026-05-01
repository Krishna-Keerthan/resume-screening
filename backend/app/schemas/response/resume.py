"""
app/schemas/response/resume.py — Resume response serialisation schemas.
"""

from marshmallow import fields

from app.schemas.base import BaseSchema


class ResumeResponseSchema(BaseSchema):
    """Full resume record — used for GET /resumes/<id>."""

    id           = fields.String()
    candidate_id = fields.String()
    filename     = fields.String()
    file_type    = fields.String()
    file_size_kb = fields.Integer(dump_default=None)

    # Parsed content
    skills         = fields.List(fields.String(),  dump_default=[])
    education      = fields.List(fields.Dict(),    dump_default=[])
    experience     = fields.List(fields.Dict(),    dump_default=[])
    certifications = fields.List(fields.String(),  dump_default=[])
    projects       = fields.List(fields.Dict(),    dump_default=[])
    summary_text   = fields.String(dump_default=None)

    # Metrics
    total_experience_years = fields.Float()
    skill_count            = fields.Integer()

    # Analysis results
    resume_summary    = fields.String(dump_default=None)
    issues_detected   = fields.List(fields.Dict(),  dump_default=[])
    role_suggestions  = fields.List(fields.Dict(),  dump_default=[])
    improvement_tips  = fields.List(fields.Dict(),  dump_default=[])

    parse_status    = fields.String()
    parse_error_msg = fields.String(dump_default=None)
    is_active       = fields.Boolean()

    created_at = fields.String()
    updated_at = fields.String()


class ResumeListSchema(BaseSchema):
    """Compact resume record — omits raw_text and analysis fields."""

    id           = fields.String()
    candidate_id = fields.String()
    filename     = fields.String()
    file_type    = fields.String()
    file_size_kb = fields.Integer(dump_default=None)
    total_experience_years = fields.Float()
    skill_count  = fields.Integer()
    parse_status = fields.String()
    is_active    = fields.Boolean()
    created_at   = fields.String()


class ResumeAnalysisSchema(BaseSchema):
    """
    Analysis-only response — used for POST /resumes/<id>/analyze.

    Returns the AI analysis output without the raw file content.
    """

    id           = fields.String()
    candidate_id = fields.String()
    skills       = fields.List(fields.String(), dump_default=[])

    resume_summary    = fields.String(dump_default=None)
    issues_detected   = fields.List(fields.Dict(), dump_default=[])
    role_suggestions  = fields.List(fields.Dict(), dump_default=[])
    improvement_tips  = fields.List(fields.Dict(), dump_default=[])

    # Meta
    analysis_cached = fields.Boolean(dump_default=False)
    # True when returning previously computed results
