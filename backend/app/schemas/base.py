"""
app/schemas/base.py

Base Marshmallow schema configuration shared by all schemas.

Design:
  - EXCLUDE unknown fields by default (don't silently accept garbage input).
  - load() returns Python dicts (not model instances) — services handle construction.
  - CamelCase → snake_case conversion helpers for frontend interop (optional).

Usage:
    from app.schemas.base import BaseSchema
    from marshmallow import fields, validate

    class MySchema(BaseSchema):
        name = fields.String(required=True)
"""

from marshmallow import Schema, pre_load


class BaseSchema(Schema):
    """
    Base schema for all request/response schemas.

    Configuration:
      - unknown=EXCLUDE: Strip fields not declared in the schema.
        This prevents unexpected data from reaching the service layer.
    """

    class Meta:
        # Strip unknown fields instead of raising an error.
        # Change to RAISE if you want strict validation during development.
        from marshmallow import EXCLUDE
        unknown = EXCLUDE

    @pre_load
    def _strip_strings(self, data: dict, **kwargs) -> dict:
        """
        Strip leading/trailing whitespace from all string values before validation.
        Prevents '  admin  ' from passing where 'admin' is the valid value.
        """
        if not isinstance(data, dict):
            return data
        return {
            k: (v.strip() if isinstance(v, str) else v)
            for k, v in data.items()
        }
