
"""
tests/unit/test_exceptions.py

Unit tests for the custom exception hierarchy.
"""
import pytest


class TestBaseApiException:
    def test_has_message(self, app):
        with app.app_context():
            from app.core.exceptions import APIException
            exc = APIException("Something went wrong", status_code=500)
            assert exc.message == "Something went wrong"
            assert exc.status_code == 500

    def test_default_error_code(self, app):
        with app.app_context():
            from app.core.exceptions import APIException
            exc = APIException("error")
            assert exc.error_code is not None

    def test_to_dict(self, app):
        with app.app_context():
            from app.core.exceptions import APIException
            exc = APIException("msg", error_code="TEST_ERR", status_code=400)
            d = exc.to_dict()
            assert d["error"]["error_code"] == "TEST_ERR"
            assert d["error"]["message"] == "msg"
            assert d["success"] is False


class TestDomainExceptions:
    def test_not_found_exception(self, app):
        with app.app_context():
            from app.core.exceptions import NotFoundException
            exc = NotFoundException("Candidate not found", error_code="CANDIDATE_NOT_FOUND")
            assert exc.status_code == 404

    def test_conflict_exception(self, app):
        with app.app_context():
            from app.core.exceptions import ConflictException
            exc = ConflictException("Duplicate", error_code="DUPE")
            assert exc.status_code == 409

    def test_validation_exception(self, app):
        with app.app_context():
            from app.core.exceptions import ValidationException
            exc = ValidationException("Bad input", error_code="INVALID")
            assert exc.status_code == 400

    def test_unprocessable_exception(self, app):
        with app.app_context():
            from app.core.exceptions import UnprocessableException
            exc = UnprocessableException("Cannot process", error_code="NOPE")
            assert exc.status_code == 422

    def test_forbidden_exception(self, app):
        with app.app_context():
            from app.core.exceptions import ForbiddenException
            exc = ForbiddenException("Access denied", error_code="FORBIDDEN")
            assert exc.status_code == 403