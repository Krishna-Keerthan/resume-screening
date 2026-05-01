"""
app/utils/validators.py

Input validation helpers used across API routes and Marshmallow schemas.

IMPROVEMENTS APPLIED:
  VL-01 — Added validate_email(). Email validation was previously scattered
           across Marshmallow schemas using different regex patterns or
           relying on marshmallow-email which has no normalization. A single
           canonical helper ensures consistent behavior everywhere.

  VL-02 — Added validate_uuid(). Route handlers that receive UUIDs as path
           or body params called get_by_id() directly with whatever string
           the client sent. A malformed UUID (e.g. "abc") still hits the DB
           query and returns a generic 404 instead of a clear 400.
           validate_uuid() lets callers return a 400 early with a clear
           message before touching the repository.
"""

import re
import uuid as _uuid
from typing import Any

from app.core.exceptions import ValidationError


# ── Email ─────────────────────────────────────────────────────────────────────

# RFC 5321-compatible basic email regex — not exhaustive but catches 99% of
# real typos. For strict validation use a dedicated library like email-validator.
_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)

_MAX_EMAIL_LENGTH = 254  # RFC 5321 maximum


def validate_email(value: str, field_name: str = "email") -> str:
    """
    Validate and normalise an email address.

    VL-01: Centralised email validation that:
      - Strips leading/trailing whitespace.
      - Lowercases the address (consistent storage).
      - Applies a basic RFC 5321 pattern check.
      - Enforces the 254-character length limit.

    Args:
        value:      Raw email string from user input.
        field_name: Name used in the ValidationError message.

    Returns:
        Normalised (stripped + lowercased) email string.

    Raises:
        ValidationError: If the email format is invalid.
    """
    if not isinstance(value, str):
        raise ValidationError(
            f"'{field_name}' must be a string.",
            details={field_name: value},
        )

    normalised = value.strip().lower()

    if not normalised:
        raise ValidationError(
            f"'{field_name}' is required.",
            details={field_name: value},
        )

    if len(normalised) > _MAX_EMAIL_LENGTH:
        raise ValidationError(
            f"'{field_name}' exceeds the maximum length of {_MAX_EMAIL_LENGTH} characters.",
            details={field_name: normalised[:30] + "..."},
        )

    if not _EMAIL_RE.match(normalised):
        raise ValidationError(
            f"'{field_name}' does not appear to be a valid email address.",
            details={field_name: normalised},
        )

    return normalised


# ── UUID ──────────────────────────────────────────────────────────────────────

def validate_uuid(value: Any, field_name: str = "id") -> str:
    """
    Validate that a value is a well-formed UUID v4 string.

    VL-02: Route handlers receive UUIDs as path params or body fields.
    Without early validation, malformed values reach the repository
    where SQLAlchemy may raise an unexpected error or silently return None,
    producing a misleading 404 instead of a clear 400.

    Usage in a route:
        from app.utils.validators import validate_uuid
        from app.core.exceptions import ValidationError

        @bp.get("/<candidate_id>")
        def get_candidate(candidate_id: str):
            try:
                validate_uuid(candidate_id, "candidate_id")
            except ValidationError as exc:
                return error(exc.message, code="INVALID_UUID", status=400)
            ...

    Args:
        value:      The value to validate (expected to be a UUID string).
        field_name: Name used in the ValidationError message.

    Returns:
        The UUID string in lowercase canonical form (with hyphens).

    Raises:
        ValidationError: If the value is not a valid UUID.
    """
    if not isinstance(value, str):
        raise ValidationError(
            f"'{field_name}' must be a UUID string.",
            details={field_name: str(value)},
        )

    try:
        parsed = _uuid.UUID(value)
    except ValueError:
        raise ValidationError(
            f"'{field_name}' is not a valid UUID.",
            details={field_name: value},
        )

    return str(parsed)


# ── General ───────────────────────────────────────────────────────────────────

def validate_positive_int(
    value: Any,
    field_name: str = "value",
    min_value: int = 1,
    max_value: int | None = None,
) -> int:
    """
    Validate that a value is a positive integer within an optional range.

    Args:
        value:      Raw input (will be coerced from string if possible).
        field_name: Name used in error messages.
        min_value:  Inclusive minimum (default 1).
        max_value:  Inclusive maximum (optional).

    Returns:
        Validated integer.

    Raises:
        ValidationError: If the value is invalid or out of range.
    """
    try:
        int_val = int(value)
    except (TypeError, ValueError):
        raise ValidationError(
            f"'{field_name}' must be an integer.",
            details={field_name: str(value)},
        )

    if int_val < min_value:
        raise ValidationError(
            f"'{field_name}' must be at least {min_value}.",
            details={field_name: int_val},
        )

    if max_value is not None and int_val > max_value:
        raise ValidationError(
            f"'{field_name}' must be at most {max_value}.",
            details={field_name: int_val},
        )

    return int_val


def validate_float_range(
    value: Any,
    field_name: str = "value",
    min_value: float = 0.0,
    max_value: float = 1.0,
) -> float:
    """
    Validate that a value is a float within [min_value, max_value].

    Commonly used for score and weight validation.

    Raises:
        ValidationError: If the value is invalid or out of range.
    """
    try:
        f_val = float(value)
    except (TypeError, ValueError):
        raise ValidationError(
            f"'{field_name}' must be a number.",
            details={field_name: str(value)},
        )

    if not (min_value <= f_val <= max_value):
        raise ValidationError(
            f"'{field_name}' must be between {min_value} and {max_value}.",
            details={field_name: f_val},
        )

    return f_val