"""
tests/unit/test_exceptions.py

Unit tests for the custom exception hierarchy.
"""


class TestAppError:
    def test_has_message(self):
        from app.core.exceptions import AppError
        exc = AppError("Something went wrong")
        assert exc.message == "Something went wrong"
        assert exc.status_code == 500

    def test_default_error_code(self):
        from app.core.exceptions import AppError
        assert AppError("error").error_code == "INTERNAL_ERROR"

    def test_to_dict(self):
        from app.core.exceptions import AppError
        d = AppError("msg", details={"k": "v"}).to_dict()
        assert d == {"error_code": "INTERNAL_ERROR", "message": "msg", "details": {"k": "v"}}

    def test_to_dict_omits_empty_details(self):
        from app.core.exceptions import AppError
        assert "details" not in AppError("msg").to_dict()


class TestDomainExceptions:
    def test_not_found_exception(self):
        from app.core.exceptions import NotFoundError
        assert NotFoundError("Candidate not found").status_code == 404

    def test_conflict_exception(self):
        from app.core.exceptions import ConflictError
        assert ConflictError("Duplicate").status_code == 409

    def test_validation_exception(self):
        from app.core.exceptions import ValidationError
        exc = ValidationError("Bad input", field="email")
        assert exc.status_code == 400
        assert exc.details["field"] == "email"

    def test_business_rule_exception(self):
        from app.core.exceptions import BusinessRuleError
        assert BusinessRuleError("Cannot process").status_code == 422

    def test_candidate_not_found_carries_id(self):
        from app.core.exceptions import CandidateNotFound
        exc = CandidateNotFound("abc")
        assert exc.status_code == 404
        assert exc.error_code == "CANDIDATE_NOT_FOUND"
        assert exc.details == {"candidate_id": "abc"}
