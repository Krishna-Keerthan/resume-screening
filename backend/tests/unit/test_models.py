
"""
tests/unit/test_models.py

Unit tests for SQLAlchemy models — basic ORM operations, 
soft-delete, JSON property accessors, and relationships.
"""
import uuid
import pytest


class TestCandidateModel:
    def test_create_candidate(self, db, app, sample_candidate):
        with app.app_context():
            assert sample_candidate.id is not None
            assert sample_candidate.full_name == "Jane Doe"

    def test_preferred_roles_roundtrip(self, db, app, sample_candidate):
        with app.app_context():
            roles = sample_candidate.preferred_roles_list
            assert isinstance(roles, list)
            assert "Backend Engineer" in roles

    def test_preferred_locations_roundtrip(self, db, app, sample_candidate):
        with app.app_context():
            locs = sample_candidate.preferred_locations_list
            assert "Remote" in locs

    def test_soft_delete(self, db, app, sample_candidate):
        with app.app_context():
            assert sample_candidate.is_alive() is True
            sample_candidate.soft_delete()
            assert sample_candidate.is_deleted is True
            assert sample_candidate.is_alive() is False

    def test_restore(self, db, app, sample_candidate):
        with app.app_context():
            sample_candidate.soft_delete()
            sample_candidate.restore()
            assert sample_candidate.is_deleted is False
            assert sample_candidate.is_alive() is True

    def test_to_dict_contains_expected_keys(self, db, app, sample_candidate):
        with app.app_context():
            d = sample_candidate.to_dict()
            for key in ("id", "full_name", "email", "location", "open_to_work", "created_at"):
                assert key in d

    def test_to_dict_excludes_requested_key(self, db, app, sample_candidate):
        with app.app_context():
            d = sample_candidate.to_dict(exclude={"email"})
            assert "email" not in d

    def test_email_stored_as_lowercase(self, db, app, sample_candidate):
        with app.app_context():
            assert sample_candidate.email == sample_candidate.email.lower()


class TestRecruiterModel:
    def test_create_recruiter(self, db, app, sample_recruiter):
        with app.app_context():
            assert sample_recruiter.id is not None
            assert sample_recruiter.company_name == "TechCorp Pvt Ltd"

    def test_soft_delete(self, db, app, sample_recruiter):
        with app.app_context():
            sample_recruiter.soft_delete()
            assert sample_recruiter.is_deleted is True

    def test_to_dict_keys(self, db, app, sample_recruiter):
        with app.app_context():
            d = sample_recruiter.to_dict()
            for key in ("id", "full_name", "email", "company_name", "industry"):
                assert key in d


class TestJobModel:
    def test_create_job(self, db, app, sample_job):
        with app.app_context():
            assert sample_job.id is not None
            assert sample_job.title == "Senior Python Developer"
            assert sample_job.status == "active"

    def test_required_skills_roundtrip(self, db, app, sample_job):
        with app.app_context():
            skills = sample_job.required_skills_list
            assert "Python" in skills
            assert "Flask" in skills

    def test_nice_to_have_skills_roundtrip(self, db, app, sample_job):
        with app.app_context():
            skills = sample_job.nice_to_have_skills_list
            assert "Kubernetes" in skills

    def test_soft_delete_job(self, db, app, sample_job):
        with app.app_context():
            sample_job.soft_delete()
            assert sample_job.is_deleted is True

    def test_to_dict_has_recruiter_id(self, db, app, sample_job):
        with app.app_context():
            d = sample_job.to_dict()
            assert "recruiter_id" in d
            assert d["recruiter_id"] == sample_job.recruiter_id


class TestResumeModel:
    def test_create_resume(self, db, app, sample_resume):
        with app.app_context():
            assert sample_resume.id is not None
            assert sample_resume.parse_status == "success"

    def test_skills_list_roundtrip(self, db, app, sample_resume):
        with app.app_context():
            skills = sample_resume.skills_list
            assert "Python" in skills
            assert "Flask" in skills

    def test_education_list_roundtrip(self, db, app, sample_resume):
        with app.app_context():
            edu = sample_resume.education_list
            assert isinstance(edu, list)
            assert edu[0]["degree"] == "B.Tech"

    def test_experience_list_roundtrip(self, db, app, sample_resume):
        with app.app_context():
            exp = sample_resume.experience_list
            assert len(exp) == 2
            titles = [e["title"] for e in exp]
            assert "Senior Dev" in titles

    def test_certifications_roundtrip(self, db, app, sample_resume):
        with app.app_context():
            certs = sample_resume.certifications_list
            assert "AWS Certified Developer" in certs

    def test_candidate_link(self, db, app, sample_resume, sample_candidate):
        with app.app_context():
            assert sample_resume.candidate_id == sample_candidate.id

    def test_to_dict_has_parse_status(self, db, app, sample_resume):
        with app.app_context():
            d = sample_resume.to_dict()
            assert d["parse_status"] == "success"


class TestApplicationModel:
    def test_create_application(self, db, app, sample_application):
        with app.app_context():
            assert sample_application.id is not None
            assert sample_application.stage == "applied"

    def test_advance_stage(self, db, app, sample_application):
        with app.app_context():
            sample_application.advance_stage("reviewed")
            assert sample_application.stage == "reviewed"

    def test_stage_history_appended(self, db, app, sample_application):
        with app.app_context():
            sample_application.advance_stage("reviewed")
            history = sample_application.stage_history_list
            stages = [h["stage"] for h in history]
            assert "reviewed" in stages

    def test_multiple_stage_advances(self, db, app, sample_application):
        with app.app_context():
            for stage in ["reviewed", "shortlisted"]:
                sample_application.advance_stage(stage)
            assert sample_application.stage == "shortlisted"

    def test_to_dict_keys(self, db, app, sample_application):
        with app.app_context():
            d = sample_application.to_dict()
            for key in ("id", "candidate_id", "job_id", "resume_id", "stage"):
                assert key in d