"""
app/schemas/auth.py

Marshmallow schemas for /api/v1/auth/* endpoints.

Schemas:
  RegisterCandidateSchema — POST /auth/register/candidate
  RegisterRecruiterSchema — POST /auth/register/recruiter
  LoginSchema             — POST /auth/login
  RefreshSchema           — POST /auth/refresh  (reads cookie, no body needed
                             but body-based fallback is supported for testing)
  ChangePasswordSchema    — POST /auth/change-password
"""

import re

from marshmallow import ValidationError, fields, validate, validates

from app.schemas.base import BaseSchema

_VALID_ROLES   = ("candidate", "recruiter")
_MIN_PW_LEN    = 8
_MAX_PW_LEN    = 128

# Password strength: at least one upper, one lower, one digit, one special char
_PW_PATTERN = re.compile(
    r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?]).+$"
)


def _validate_password_strength(value: str) -> None:
    """
    Shared password validator used by register and change-password schemas.
    Raises ValidationError with specific guidance on failure.
    """
    if len(value) < _MIN_PW_LEN:
        raise ValidationError(f"Password must be at least {_MIN_PW_LEN} characters.")
    if len(value) > _MAX_PW_LEN:
        raise ValidationError(f"Password must be at most {_MAX_PW_LEN} characters.")
    if not _PW_PATTERN.match(value):
        raise ValidationError(
            "Password must contain at least one uppercase letter, "
            "one lowercase letter, one digit, and one special character."
        )


class RegisterCandidateSchema(BaseSchema):
    """
    Validates POST /api/v1/auth/register/candidate.

    Required : full_name, email, password
    Optional : phone, location, headline, open_to_work,
               preferred_roles, preferred_locations,
               linkedin_url, github_url, portfolio_url
    """

    full_name = fields.String(
        required=True,
        validate=validate.Length(min=1, max=200),
        error_messages={"required": "full_name is required."},
    )
    email = fields.Email(
        required=True,
        error_messages={"required": "Email is required.", "invalid": "Enter a valid email address."},
    )
    password = fields.String(
        required=True,
        load_only=True,             # never serialise back
        validate=_validate_password_strength,
        error_messages={"required": "Password is required."},
    )

    # Optional profile fields
    phone        = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=30))
    location     = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=200))
    headline     = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=300))
    open_to_work        = fields.Boolean(load_default=True)
    preferred_roles     = fields.List(fields.String(), load_default=[])
    preferred_locations = fields.List(fields.String(), load_default=[])
    linkedin_url  = fields.Url(load_default=None, allow_none=True)
    github_url    = fields.Url(load_default=None, allow_none=True)
    portfolio_url = fields.Url(load_default=None, allow_none=True)


class RegisterRecruiterSchema(BaseSchema):
    """
    Validates POST /api/v1/auth/register/recruiter.

    Required : full_name, email, password, company_name
    Optional : company_size, industry, phone, website_url, linkedin_url
    """

    full_name = fields.String(
        required=True,
        validate=validate.Length(min=1, max=200),
        error_messages={"required": "full_name is required."},
    )
    email = fields.Email(
        required=True,
        error_messages={"required": "Email is required.", "invalid": "Enter a valid email address."},
    )
    password = fields.String(
        required=True,
        load_only=True,
        validate=_validate_password_strength,
        error_messages={"required": "Password is required."},
    )
    company_name = fields.String(
        required=True,
        validate=validate.Length(min=1, max=300),
        error_messages={"required": "company_name is required."},
    )
    company_size = fields.String(
        load_default=None,
        allow_none=True,
        validate=validate.OneOf(
            ["1-10", "11-50", "51-200", "201-500", "500+"],
            error="company_size must be one of: 1-10, 11-50, 51-200, 201-500, 500+.",
        ),
    )
    industry     = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=100))
    phone        = fields.String(load_default=None, allow_none=True, validate=validate.Length(max=30))
    website_url  = fields.Url(load_default=None, allow_none=True)
    linkedin_url = fields.Url(load_default=None, allow_none=True)


class LoginSchema(BaseSchema):
    """
    Validates POST /api/v1/auth/login.

    Fields:
        email    — normalised to lowercase in the view layer
        password — load_only, never echoed back
        role     — 'candidate' | 'recruiter'
    """

    email = fields.Email(
        required=True,
        error_messages={"required": "Email is required.", "invalid": "Enter a valid email address."},
    )
    password = fields.String(
        required=True,
        load_only=True,
        error_messages={"required": "Password is required."},
    )
    role = fields.String(
        required=True,
        validate=validate.OneOf(_VALID_ROLES, error="role must be 'candidate' or 'recruiter'."),
        error_messages={"required": "role is required."},
    )


class ChangePasswordSchema(BaseSchema):
    """
    Validates POST /api/v1/auth/change-password.

    Requires the current password for re-authentication before allowing
    a change — prevents session hijacking attacks.
    """

    current_password = fields.String(
        required=True,
        load_only=True,
        error_messages={"required": "current_password is required."},
    )
    new_password = fields.String(
        required=True,
        load_only=True,
        validate=_validate_password_strength,
        error_messages={"required": "new_password is required."},
    )

    @validates("new_password")
    def new_differs_from_current(self, value: str) -> None:
        """Prevent reuse of the current password."""
        # Note: full equality check happens in the view layer (requires DB lookup).
        # Here we only do lightweight format validation.
        pass  # placeholder for additional cross-field rules if needed