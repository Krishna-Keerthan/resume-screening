"""
tests/conftest.py  —  Phase 5 shared fixtures.
"""

import io
import json
import os
import uuid
from unittest.mock import MagicMock, patch

import pytest
from flask.testing import FlaskClient

from app import create_app
from app.core.database import db as _db


# ─── Infrastructure ───────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def app():
    os.environ["APP_ENV"] = "testing"
    with patch("app.services.service_factory.ServiceFactory.create_all") as mock_factory:
        mock_svcs = MagicMock()
        mock_svcs.groq.available = False
        mock_svcs.embedding.available = False
        mock_factory.return_value = mock_svcs
        flask_app = create_app("testing")

    with flask_app.app_context():
        _db.create_all()
        yield flask_app
        _db.drop_all()


@pytest.fixture()
def db(app):
    with app.app_context():
        connection = _db.engine.connect()
        transaction = connection.begin()
        _db.session.configure(bind=connection)
        yield _db
        _db.session.remove()
        transaction.rollback()
        connection.close()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def json_post(client):
    def _post(url, body=None, **kw):
        r = client.post(url, data=json.dumps(body or {}),
                        content_type="application/json", **kw)
        return r, r.get_json()
    return _post


@pytest.fixture()
def json_patch(client):
    def _patch(url, body=None, **kw):
        r = client.patch(url, data=json.dumps(body or {}),
                         content_type="application/json", **kw)
        return r, r.get_json()
    return _patch


@pytest.fixture()
def json_get(client):
    def _get(url, params=None, **kw):
        qs = ("?" + "&".join(f"{k}={v}" for k, v in params.items())) if params else ""
        r = client.get(url + qs, **kw)
        return r, r.get_json()
    return _get


@pytest.fixture()
def json_delete(client):
    def _delete(url, **kw):
        r = client.delete(url, **kw)
        return r, (r.get_json() if r.data else None)
    return _delete


# ─── Domain fixtures ──────────────────────────────────────────────────────────

@pytest.fixture()
def sample_candidate(db, app):
    from app.models.candidate import Candidate
    with app.app_context():
        c = Candidate(
            full_name="Jane Doe",
            email=f"jane+{uuid.uuid4().hex[:6]}@example.com",
            phone="+91-9876543210",
            location="Chennai, India",
            headline="Senior Python Developer",
            open_to_work=True,
        )
        c.preferred_roles_list     = ["Backend Engineer", "ML Engineer"]
        c.preferred_locations_list = ["Remote", "Chennai"]
        c.save()
        _db.session.flush()
        return c


@pytest.fixture()
def sample_recruiter(db, app):
    from app.models.recruiter import Recruiter
    with app.app_context():
        r = Recruiter(
            full_name="HR Manager",
            email=f"hr+{uuid.uuid4().hex[:6]}@techcorp.com",
            company_name="TechCorp Pvt Ltd",
            company_size="51-200",
            industry="Software",
        )
        r.save()
        _db.session.flush()
        return r


@pytest.fixture()
def sample_job(db, app, sample_recruiter):
    from app.models.job import Job
    from app.models.enums import JobStatus, JobType
    with app.app_context():
        j = Job(
            title="Senior Python Developer",
            company="TechCorp Pvt Ltd",
            description=(
                "We need a Senior Python Developer with 5+ years of experience "
                "in Flask, PostgreSQL, and Docker. NLP/ML background preferred."
            ),
            experience_years=5.0,
            location="Remote",
            job_type=JobType.FULL_TIME,
            status=JobStatus.ACTIVE,
            recruiter_id=sample_recruiter.id,
        )
        j.required_skills_list     = ["Python", "Flask", "PostgreSQL", "Docker", "NLP"]
        j.nice_to_have_skills_list = ["Kubernetes", "Redis"]
        j.applicant_count          = 0
        j.save()
        _db.session.flush()
        return j


@pytest.fixture()
def sample_job_closed(db, app, sample_recruiter):
    from app.models.job import Job
    from app.models.enums import JobStatus, JobType
    with app.app_context():
        j = Job(
            title="DevOps Engineer (Filled)",
            company="TechCorp Pvt Ltd",
            description="Looking for a DevOps engineer with at least 3 years of Kubernetes experience.",
            experience_years=3.0,
            location="Bangalore, India",
            job_type=JobType.FULL_TIME,
            status=JobStatus.CLOSED,
            recruiter_id=sample_recruiter.id,
        )
        j.required_skills_list = ["Kubernetes", "Docker", "CI/CD"]
        j.save()
        _db.session.flush()
        return j


@pytest.fixture()
def sample_resume(db, app, sample_candidate):
    from app.models.resume import Resume
    from app.models.enums import ParseStatus
    with app.app_context():
        r = Resume(
            candidate_id=sample_candidate.id,
            filename="jane_doe_resume.pdf",
            file_path="/tmp/uploads/fake_resume.pdf",
            file_size_bytes=102400,
            content_type="application/pdf",
            parse_status=ParseStatus.SUCCESS,
            total_experience_years=6.0,
            is_active=True,
        )
        r.skills_list         = ["Python", "Flask", "PostgreSQL", "Docker", "NLP", "FastAPI"]
        r.education_list      = [{"degree": "B.Tech", "institution": "IIT Chennai", "year": 2018}]
        r.experience_list     = [
            {"title": "Senior Dev", "company": "StartupX", "years": 3.0},
            {"title": "Developer",  "company": "InfraY",   "years": 3.0},
        ]
        r.certifications_list = ["AWS Certified Developer"]
        r.summary_text        = "Experienced Python developer specializing in backend and ML."
        r.save()
        _db.session.flush()
        return r


@pytest.fixture()
def sample_application(db, app, sample_candidate, sample_job, sample_resume):
    from app.models.application import Application
    from app.models.enums import ApplicationStage
    with app.app_context():
        a = Application(
            candidate_id=sample_candidate.id,
            job_id=sample_job.id,
            resume_id=sample_resume.id,
            stage=ApplicationStage.APPLIED,
            cover_letter="I am very interested in this role.",
        )
        a.save()
        _db.session.flush()
        return a


# ─── Service mock ─────────────────────────────────────────────────────────────

@pytest.fixture()
def mock_services(app):
    mock_svcs = MagicMock()
    mock_svcs.groq.available      = False
    mock_svcs.embedding.available = False
    with app.app_context():
        original = app.extensions.get("services")
        app.extensions["services"] = mock_svcs
        yield mock_svcs
        app.extensions["services"] = original


@pytest.fixture()
def resume_file():
    return (io.BytesIO(b"%PDF-1.4 fake pdf content"), "test_resume.pdf")