"""
app/schemas/response/application.py — Application response serialisation schemas.
"""

from marshmallow import fields

from app.schemas.base import BaseSchema


class ApplicationResponseSchema(BaseSchema):
    """Full application record — used for GET /applications/<id>."""

    id           = fields.String()
    candidate_id = fields.String()
    job_id       = fields.String()
    resume_id    = fields.String()

    stage         = fields.String()
    stage_history = fields.List(fields.Dict(), dump_default=[])
    is_terminal   = fields.Boolean(dump_default=False)

    recruiter_notes  = fields.String(dump_default=None)
    rejection_reason = fields.String(dump_default=None)
    cover_letter     = fields.String(dump_default=None)

    created_at = fields.String()
    updated_at = fields.String()

    # Embedded ATS score summary (injected by service layer)
    ats_score = fields.Dict(dump_default=None)


class ApplicationListSchema(BaseSchema):
    """Compact applicant row — used in recruiter analytics table."""

    id           = fields.String()
    candidate_id = fields.String()
    job_id       = fields.String()
    resume_id    = fields.String()
    stage        = fields.String()
    is_terminal  = fields.Boolean()
    created_at   = fields.String()

    # Injected by service from joined AtsScore
    final_score  = fields.Float(dump_default=None)
    score_label  = fields.String(dump_default=None)
