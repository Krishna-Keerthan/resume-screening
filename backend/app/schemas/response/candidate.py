"""
app/schemas/response/candidate.py — Candidate response serialisation schemas.

Design:
  - CandidateResponseSchema: Full record with all fields.
  - CandidateListSchema:     Compact record for paginated list responses.
  - dump_default=None on optional fields ensures absent values serialize
    as null rather than being omitted (consistent frontend handling).
"""

from marshmallow import fields

from app.schemas.base import BaseSchema


class CandidateResponseSchema(BaseSchema):
    """Full candidate record — used for GET /candidates/<id>."""

    id           = fields.String(dump_default=None)
    full_name    = fields.String(dump_default=None)
    email        = fields.Email(dump_default=None)
    phone        = fields.String(dump_default=None)
    location     = fields.String(dump_default=None)
    headline     = fields.String(dump_default=None)

    linkedin_url   = fields.String(dump_default=None)
    github_url     = fields.String(dump_default=None)
    portfolio_url  = fields.String(dump_default=None)

    preferred_roles     = fields.List(fields.String(), dump_default=[])
    preferred_locations = fields.List(fields.String(), dump_default=[])
    open_to_work        = fields.Boolean(dump_default=True)

    created_at = fields.String(dump_default=None)
    updated_at = fields.String(dump_default=None)

    # Computed in service layer — not stored on model
    resume_count      = fields.Integer(dump_default=0)
    application_count = fields.Integer(dump_default=0)


class CandidateListSchema(BaseSchema):
    """Compact candidate record — used in paginated list responses."""

    id           = fields.String()
    full_name    = fields.String()
    email        = fields.Email()
    location     = fields.String(dump_default=None)
    headline     = fields.String(dump_default=None)
    open_to_work = fields.Boolean()
    created_at   = fields.String()
