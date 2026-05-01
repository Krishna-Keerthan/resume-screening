"""
app/schemas/response/ats_score.py — ATS Score response serialisation schemas.
"""

from marshmallow import fields

from app.schemas.base import BaseSchema


class AtsScoreResponseSchema(BaseSchema):
    """
    Full ATS score with explainability — used for POST /scores/match.

    Includes all component scores, skill lists, and improvement tips.
    This is what the candidate and recruiter see when reviewing a match.
    """

    id             = fields.String()
    resume_id      = fields.String()
    job_id         = fields.String()
    application_id = fields.String(dump_default=None)

    # Score components
    semantic_score        = fields.Float()
    keyword_score         = fields.Float()
    experience_score      = fields.Float()
    section_quality_score = fields.Float()
    final_score           = fields.Float()
    score_label           = fields.String()

    # Semantic engine status
    semantic_available = fields.Boolean()

    # Explainability
    matched_skills   = fields.List(fields.String(), dump_default=[])
    missing_skills   = fields.List(fields.String(), dump_default=[])
    extra_skills     = fields.List(fields.String(), dump_default=[])
    improvement_tips = fields.List(fields.Dict(),   dump_default=[])
    summary_text     = fields.String(dump_default=None)

    # Audit
    weights_used = fields.Dict(dump_default={})
    created_at   = fields.String()


class AtsScoreSummarySchema(BaseSchema):
    """
    Compact score summary — used in dashboard cards and applicant tables.

    Does not include explainability details (too verbose for lists).
    """

    id                    = fields.String()
    resume_id             = fields.String()
    job_id                = fields.String()
    final_score           = fields.Float()
    score_label           = fields.String()
    semantic_score        = fields.Float()
    keyword_score         = fields.Float()
    experience_score      = fields.Float()
    section_quality_score = fields.Float()
    semantic_available    = fields.Boolean()
