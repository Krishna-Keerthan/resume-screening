
"""
tests/unit/test_schemas.py  —  Marshmallow schema validation tests.
"""
import pytest


class TestCreateJobSchema:
    def test_valid_payload(self, app):
        with app.app_context():
            from app.schemas.job import CreateJobSchema
            data = CreateJobSchema().load({
                "title":       "Senior Python Developer",
                "company":     "TechCorp",
                "description": "We are looking for a Python developer with 5+ years of experience in Flask.",
                "required_skills": ["Python", "Flask"],
            })
            assert data["title"] == "Senior Python Developer"
            assert data["job_type"] == "full-time"   # default
            assert data["status"]   == "active"      # default

    def test_salary_cross_validator(self, app):
        with app.app_context():
            from marshmallow import ValidationError
            from app.schemas.job import CreateJobSchema
            with pytest.raises(ValidationError) as exc_info:
                CreateJobSchema().load({
                    "title":       "Dev",
                    "company":     "Acme",
                    "description": "A long enough description for the validator to pass.",
                    "salary_min":  100000,
                    "salary_max":  50000,
                })
            assert "salary_min" in exc_info.value.messages

    def test_invalid_job_type(self, app):
        with app.app_context():
            from marshmallow import ValidationError
            from app.schemas.job import CreateJobSchema
            with pytest.raises(ValidationError) as exc_info:
                CreateJobSchema().load({
                    "title":       "Dev",
                    "company":     "Acme",
                    "description": "A long enough description for the validator.",
                    "job_type":    "gig-economy",
                })
            assert "job_type" in exc_info.value.messages

    def test_missing_required_title(self, app):
        with app.app_context():
            from marshmallow import ValidationError
            from app.schemas.job import CreateJobSchema
            with pytest.raises(ValidationError) as exc_info:
                CreateJobSchema().load({
                    "company":     "Acme",
                    "description": "Some long description here for the company.",
                })
            assert "title" in exc_info.value.messages

    def test_description_min_length(self, app):
        with app.app_context():
            from marshmallow import ValidationError
            from app.schemas.job import CreateJobSchema
            with pytest.raises(ValidationError):
                CreateJobSchema().load({
                    "title":       "Dev",
                    "company":     "Acme",
                    "description": "Short",
                })


class TestCreateCandidateSchema:
    def test_valid_payload(self, app):
        with app.app_context():
            from app.schemas.candidate import CreateCandidateSchema
            data = CreateCandidateSchema().load({
                "full_name": "John Smith",
                "email":     "john@example.com",
            })
            assert data["full_name"] == "John Smith"
            assert data["email"] == "john@example.com"
            assert data["open_to_work"] is True   # default

    def test_email_normalised_to_lowercase(self, app):
        with app.app_context():
            from app.schemas.candidate import CreateCandidateSchema
            data = CreateCandidateSchema().load({
                "full_name": "Alice",
                "email":     "ALICE@EXAMPLE.COM",
            })
            assert data["email"] == "alice@example.com"

    def test_missing_full_name(self, app):
        with app.app_context():
            from marshmallow import ValidationError
            from app.schemas.candidate import CreateCandidateSchema
            with pytest.raises(ValidationError) as exc_info:
                CreateCandidateSchema().load({"email": "a@b.com"})
            assert "full_name" in exc_info.value.messages

    def test_invalid_email(self, app):
        with app.app_context():
            from marshmallow import ValidationError
            from app.schemas.candidate import CreateCandidateSchema
            with pytest.raises(ValidationError) as exc_info:
                CreateCandidateSchema().load({
                    "full_name": "Bob",
                    "email":     "not-an-email",
                })
            assert "email" in exc_info.value.messages


class TestCreateRecruiterSchema:
    def test_valid_payload(self, app):
        with app.app_context():
            from app.schemas.recruiter import CreateRecruiterSchema
            data = CreateRecruiterSchema().load({
                "full_name":    "HR Manager",
                "email":        "hr@corp.com",
                "company_name": "Corp Inc",
            })
            assert data["full_name"] == "HR Manager"

    def test_invalid_company_size(self, app):
        with app.app_context():
            from marshmallow import ValidationError
            from app.schemas.recruiter import CreateRecruiterSchema
            with pytest.raises(ValidationError) as exc_info:
                CreateRecruiterSchema().load({
                    "full_name":    "HR",
                    "email":        "hr@corp.com",
                    "company_name": "Corp",
                    "company_size": "gigantic",
                })
            assert "company_size" in exc_info.value.messages