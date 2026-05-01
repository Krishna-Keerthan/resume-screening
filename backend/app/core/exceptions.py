"""
app/core/exceptions.py

Domain exception hierarchy for the platform.

Design:
  - Every exception carries an HTTP status code and a machine-readable
    error_code string so the global error handler can produce uniform
    JSON responses without needing to inspect exception types in routes.
  - Subclass from AppError for all expected business errors.
  - Use Python's built-ins (ValueError, etc.) only for internal bugs.
  - The error handler in app/__init__.py catches AppError and maps it to JSON.

Exception hierarchy:
    AppError                        (base)
    ├── ValidationError  (400)
    ├── NotFoundError    (404)
    ├── ConflictError    (409)
    ├── BusinessRuleError(422)
    ├── ExternalServiceError (502)
    ├── ConfigurationError   (500)
    │
    ├── ResumeError      (400 family)
    │   ├── ResumeParseFailed      (422)
    │   ├── ResumeNotFound         (404)
    │   └── ResumeUploadFailed     (400)
    │
    ├── JobError
    │   ├── JobNotFound            (404)
    │   └── DuplicateJobError      (409)
    │
    ├── CandidateError
    │   └── CandidateNotFound      (404)
    │
    ├── RecruiterError
    │   └── RecruiterNotFound      (404)
    │
    └── ScoringError               (500)

Usage:
    raise ResumeNotFound(resume_id="abc123")
    raise ValidationError("Email is invalid", field="email")
    raise ExternalServiceError("Groq", "Timeout after 30s")
"""

from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# Base
# ─────────────────────────────────────────────────────────────────────────────

class AppError(Exception):
    """
    Base class for all application-level errors.

    Attributes:
        message:     Human-readable description (exposed in API response).
        error_code:  Machine-readable slug (e.g. "RESUME_NOT_FOUND").
        status_code: HTTP status to return.
        details:     Optional dict with extra context (field errors, etc.).
    """

    message: str = "An unexpected error occurred."
    error_code: str = "INTERNAL_ERROR"
    status_code: int = 500

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.__class__.message
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to the standard API error payload."""
        payload: dict[str, Any] = {
            "error_code": self.error_code,
            "message":    self.message,
        }
        if self.details:
            payload["details"] = self.details
        return payload


# ─────────────────────────────────────────────────────────────────────────────
# Generic HTTP-mapped exceptions
# ─────────────────────────────────────────────────────────────────────────────

class ValidationError(AppError):
    """Input failed schema / business validation. 400."""
    message = "Validation failed."
    error_code = "VALIDATION_ERROR"
    status_code = 400

    def __init__(
        self,
        message: str | None = None,
        *,
        field: str | None = None,
        errors: dict | None = None,
        details: dict | None = None,
    ) -> None:
        d = details or {}
        if field:
            d["field"] = field
        if errors:
            d["errors"] = errors
        super().__init__(message, details=d)


class NotFoundError(AppError):
    """Requested resource does not exist. 404."""
    message = "Resource not found."
    error_code = "NOT_FOUND"
    status_code = 404


class ConflictError(AppError):
    """Resource already exists or state conflict. 409."""
    message = "Resource conflict."
    error_code = "CONFLICT"
    status_code = 409


class BusinessRuleError(AppError):
    """Request is structurally valid but violates business rules. 422."""
    message = "Business rule violation."
    error_code = "BUSINESS_RULE_VIOLATION"
    status_code = 422


class ExternalServiceError(AppError):
    """A downstream service (Groq, etc.) returned an error. 502."""
    error_code = "EXTERNAL_SERVICE_ERROR"
    status_code = 502

    def __init__(self, service: str, reason: str, **kwargs: Any) -> None:
        super().__init__(
            f"External service '{service}' failed: {reason}",
            details={"service": service, "reason": reason},
            **kwargs,
        )


class ConfigurationError(AppError):
    """Missing or invalid server-side configuration. 500."""
    message = "Server misconfiguration."
    error_code = "CONFIGURATION_ERROR"
    status_code = 500


class RateLimitError(AppError):
    """Too many requests. 429."""
    message = "Too many requests. Please slow down."
    error_code = "RATE_LIMIT_EXCEEDED"
    status_code = 429


# ─────────────────────────────────────────────────────────────────────────────
# Resume domain
# ─────────────────────────────────────────────────────────────────────────────

class ResumeError(AppError):
    """Base for resume-related errors."""
    error_code = "RESUME_ERROR"
    status_code = 400


class ResumeNotFound(ResumeError):
    """Resume record not found. 404."""
    error_code = "RESUME_NOT_FOUND"
    status_code = 404

    def __init__(self, resume_id: str) -> None:
        super().__init__(
            f"Resume '{resume_id}' not found.",
            details={"resume_id": resume_id},
        )


class ResumeParseFailed(ResumeError):
    """File could not be parsed. 422."""
    error_code = "RESUME_PARSE_FAILED"
    status_code = 422

    def __init__(self, reason: str) -> None:
        super().__init__(
            f"Could not parse resume: {reason}",
            details={"reason": reason},
        )


class ResumeUploadFailed(ResumeError):
    """File upload rejected (wrong type, too large, etc.). 400."""
    error_code = "RESUME_UPLOAD_FAILED"
    status_code = 400


# ─────────────────────────────────────────────────────────────────────────────
# Job domain
# ─────────────────────────────────────────────────────────────────────────────

class JobError(AppError):
    """Base for job-related errors."""
    error_code = "JOB_ERROR"
    status_code = 400


class JobNotFound(JobError):
    """Job record not found. 404."""
    error_code = "JOB_NOT_FOUND"
    status_code = 404

    def __init__(self, job_id: str) -> None:
        super().__init__(
            f"Job '{job_id}' not found.",
            details={"job_id": job_id},
        )


class DuplicateJobError(JobError):
    """A job with the same title/company already exists. 409."""
    error_code = "DUPLICATE_JOB"
    status_code = 409


# ─────────────────────────────────────────────────────────────────────────────
# Candidate domain
# ─────────────────────────────────────────────────────────────────────────────

class CandidateError(AppError):
    """Base for candidate-related errors."""
    error_code = "CANDIDATE_ERROR"
    status_code = 400


class CandidateNotFound(CandidateError):
    """Candidate profile not found. 404."""
    error_code = "CANDIDATE_NOT_FOUND"
    status_code = 404

    def __init__(self, candidate_id: str) -> None:
        super().__init__(
            f"Candidate '{candidate_id}' not found.",
            details={"candidate_id": candidate_id},
        )


# ─────────────────────────────────────────────────────────────────────────────
# Recruiter domain
# ─────────────────────────────────────────────────────────────────────────────

class RecruiterError(AppError):
    """Base for recruiter-related errors."""
    error_code = "RECRUITER_ERROR"
    status_code = 400


class RecruiterNotFound(RecruiterError):
    """Recruiter profile not found. 404."""
    error_code = "RECRUITER_NOT_FOUND"
    status_code = 404

    def __init__(self, recruiter_id: str) -> None:
        super().__init__(
            f"Recruiter '{recruiter_id}' not found.",
            details={"recruiter_id": recruiter_id},
        )


# ─────────────────────────────────────────────────────────────────────────────
# Scoring / ML domain
# ─────────────────────────────────────────────────────────────────────────────

class ScoringError(AppError):
    """Scoring or ML pipeline failed unexpectedly. 500."""
    message = "Scoring pipeline encountered an error."
    error_code = "SCORING_ERROR"
    status_code = 500


class EmbeddingError(AppError):
    """Embedding model failed. 500."""
    message = "Embedding generation failed."
    error_code = "EMBEDDING_ERROR"
    status_code = 500