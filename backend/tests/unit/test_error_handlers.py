"""
Every AppError subclass, raised from a route, becomes its own status code and the standard
JSON error envelope.

The routes run on a bare Flask app with the application's real error handlers
(_register_error_handlers), so the handler's logging, serialisation and headers are
exercised for each class. An earlier bug in the handler's log call (an `extra` key that
clashed with a LogRecord attribute) raised inside the handler and turned every domain error
into a 500; no test raised the domain errors through a route, so it went unnoticed.

EXPECTED is the contract, written out: adding or changing a subclass means changing it here.
"""
import inspect
import logging

import pytest
from flask import Flask

import app.core.exceptions as exceptions
from app import _register_error_handlers
from app.core.exceptions import AppError


def _all_subclasses(cls):
    for sub in cls.__subclasses__():
        yield sub
        yield from _all_subclasses(sub)


EXPECTED = {
    "ValidationError":      (400, "VALIDATION_ERROR"),
    "NotFoundError":        (404, "NOT_FOUND"),
    "ConflictError":        (409, "CONFLICT"),
    "BusinessRuleError":    (422, "BUSINESS_RULE_VIOLATION"),
    "ExternalServiceError": (502, "EXTERNAL_SERVICE_ERROR"),
    "ConfigurationError":   (500, "CONFIGURATION_ERROR"),
    "RateLimitError":       (429, "RATE_LIMIT_EXCEEDED"),
    "ResumeError":          (400, "RESUME_ERROR"),
    "ResumeNotFound":       (404, "RESUME_NOT_FOUND"),
    "ResumeParseFailed":    (422, "RESUME_PARSE_FAILED"),
    "ResumeUploadFailed":   (400, "RESUME_UPLOAD_FAILED"),
    "ResumeParserBusy":     (503, "PARSER_BUSY"),
    "JobError":             (400, "JOB_ERROR"),
    "JobNotFound":          (404, "JOB_NOT_FOUND"),
    "DuplicateJobError":    (409, "DUPLICATE_JOB"),
    "CandidateError":       (400, "CANDIDATE_ERROR"),
    "CandidateNotFound":    (404, "CANDIDATE_NOT_FOUND"),
    "RecruiterError":       (400, "RECRUITER_ERROR"),
    "RecruiterNotFound":    (404, "RECRUITER_NOT_FOUND"),
    "ScoringError":         (500, "SCORING_ERROR"),
    "EmbeddingError":       (500, "EMBEDDING_ERROR"),
}

SUBCLASSES = {c.__name__: c for c in _all_subclasses(AppError)}


def _instance(cls):
    """Build the error with a dummy value for each required constructor argument."""
    required = [
        p for p in inspect.signature(cls.__init__).parameters.values()
        if p.name != "self" and p.default is p.empty
        and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    return cls(*["dummy"] * len(required))


@pytest.fixture(scope="module")
def raising_client():
    flask_app = Flask(__name__)
    _register_error_handlers(flask_app)

    @flask_app.get("/raise/<name>")
    def raise_it(name):
        raise _instance(SUBCLASSES[name])

    return flask_app.test_client()


def test_the_contract_lists_every_app_error_subclass():
    assert set(EXPECTED) == set(SUBCLASSES)
    assert len(SUBCLASSES) >= 20      # discovery found the classes, not an empty set


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_each_error_has_its_own_status_and_the_standard_envelope(raising_client, name, caplog):
    status, code = EXPECTED[name]
    expected_message = str(_instance(SUBCLASSES[name]))

    with caplog.at_level(logging.WARNING):
        response = raising_client.get(f"/raise/{name}")

    assert response.status_code == status
    assert response.is_json
    body = response.get_json()
    assert body["success"] is False
    assert body["error"]["error_code"] == code
    assert body["error"]["message"] == expected_message
    assert set(body) == {"success", "error"}
    assert set(body["error"]) <= {"error_code", "message", "details"}


def test_the_handler_logs_each_error_once_with_its_code_and_status(raising_client, caplog):
    with caplog.at_level(logging.WARNING):
        raising_client.get("/raise/JobNotFound")

    (record,) = [r for r in caplog.records if r.getMessage() == "Application error"]
    assert (record.error_code, record.status_code) == ("JOB_NOT_FOUND", 404)


def test_a_busy_parser_tells_the_client_when_to_retry(raising_client):
    response = raising_client.get("/raise/ResumeParserBusy")

    assert response.headers["Retry-After"] == "5"


def test_other_errors_send_no_retry_after_header(raising_client):
    assert "Retry-After" not in raising_client.get("/raise/JobNotFound").headers
