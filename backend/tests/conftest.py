"""
tests/conftest.py  —  Phase 5 shared fixtures.
"""

import io
import json
import os
import uuid
from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy as sa
from flask.testing import FlaskClient
from flask_sqlalchemy.session import Session as FlaskSQLAlchemySession
from sqlalchemy import orm as sa_orm

from app import create_app
from app.core.database import db as _db
from config.settings import TestingConfig


# ─── Infrastructure ───────────────────────────────────────────────────────────

def pytest_addoption(parser):
    parser.addoption("--run-slow", action="store_true", default=False,
                     help="run tests marked slow (they load real ML models)")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-slow"):
        return
    skip_slow = pytest.mark.skip(reason="slow: needs --run-slow")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip_slow)


@pytest.fixture(scope="session")
def app():
    os.environ["APP_ENV"] = "testing"
    # TEST_DATABASE_URL (not DATABASE_URL) so a dev/prod DATABASE_URL in the
    # environment can never be dropped by the suite. Unset → in-memory SQLite.
    test_db_url = os.getenv("TEST_DATABASE_URL")
    db_uri = test_db_url or TestingConfig.SQLALCHEMY_DATABASE_URI
    with patch("app.services.service_factory.ServiceFactory.create_all") as mock_factory, \
         patch.object(TestingConfig, "SQLALCHEMY_DATABASE_URI", db_uri):
        mock_svcs = MagicMock()
        mock_svcs.groq.available = False
        mock_svcs.embedding.available = False
        mock_factory.return_value = mock_svcs
        flask_app = create_app("testing")

    with flask_app.app_context():
        if _db.engine.dialect.name == "sqlite":
            _enable_sqlite_savepoints(_db.engine)
        _db.create_all()
        yield flask_app
        _db.drop_all()


def _enable_sqlite_savepoints(engine):
    # pysqlite's own transaction handling breaks SAVEPOINT; let SQLAlchemy
    # emit BEGIN itself (SQLAlchemy docs: "Serializable isolation /
    # Savepoints / Transactional DDL").
    @sa.event.listens_for(engine, "connect")
    def _connect(dbapi_connection, _record):
        dbapi_connection.isolation_level = None

    @sa.event.listens_for(engine, "begin")
    def _begin(connection):
        connection.exec_driver_sql("BEGIN")


class _ConnectionBoundSession(FlaskSQLAlchemySession):
    # Flask-SQLAlchemy's get_bind ignores the session's `bind`; honour it so
    # every session in a test uses the test's connection.
    def get_bind(self, *args, **kwargs):
        return self.bind


@pytest.fixture()
def db(app):
    """
    One outer transaction per test, rolled back at the end.

    Fixtures, the test body and request handlers all share a session bound to
    the same connection; their commits only release savepoints.
    """
    with app.app_context():
        connection = _db.engine.connect()
        transaction = connection.begin()
        original_session = _db.session
        _db.session = sa_orm.scoped_session(
            sa_orm.sessionmaker(
                class_=_ConnectionBoundSession,
                db=_db,
                bind=connection,
                query_cls=_db.Query,
                join_transaction_mode="create_savepoint",
            ),
            scopefunc=original_session.registry.scopefunc,
        )
        try:
            yield _db
        finally:
            _db.session.remove()
            _db.session = original_session
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
def make_candidate(db):
    """Factory: make_candidate(**overrides) -> a flushed Candidate."""
    from app.models.candidate import Candidate

    def _make(**overrides):
        fields = {
            "full_name": "Test Candidate",
            "email": f"cand+{uuid.uuid4().hex[:8]}@example.com",
            "location": "Bangalore, India",
            "headline": "Python Developer",
            "open_to_work": True,
        }
        fields.update(overrides)
        c = Candidate(**fields)
        c.save()
        return c
    return _make


@pytest.fixture()
def make_resume(db):
    """Factory: make_resume(candidate_id=..., **overrides) -> a flushed Resume."""
    from app.models.resume import Resume
    from app.models.enums import ParseStatus

    def _make(candidate_id, **overrides):
        fields = {
            "candidate_id": candidate_id,
            "filename": "resume.pdf",
            "file_path": "/tmp/uploads/resume.pdf",
            "file_size_kb": 50,
            "file_type": "pdf",
            "parse_status": ParseStatus.SUCCESS,
        }
        fields.update(overrides)
        r = Resume(**fields)
        r.save()
        return r
    return _make


@pytest.fixture()
def sample_recruiter(db, app):
    from app.models.recruiter import Recruiter
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
    r = Resume(
        candidate_id=sample_candidate.id,
        filename="jane_doe_resume.pdf",
        file_path="/tmp/uploads/fake_resume.pdf",
        file_size_kb=100,
        file_type="pdf",
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


# ─── Authenticated actors (Phase 1 harness) ──────────────────────────────────

ACCOUNT_PASSWORD = "SecureP@ss1"

# These fixtures commit (the test session's commit only releases a savepoint):
# the app rolls the session back after every non-2xx response, which would
# otherwise discard flushed-but-uncommitted rows between the requests of one test.


@pytest.fixture()
def account_password():
    """The plaintext password of every candidate_*/recruiter_* fixture."""
    return ACCOUNT_PASSWORD


def _new_candidate(label):
    from app.core.security import hash_password
    from app.models.candidate import Candidate
    c = Candidate(
        full_name=f"Candidate {label}",
        email=f"cand-{label}-{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password(ACCOUNT_PASSWORD),
        headline="Python Developer",
        open_to_work=True,
    )
    c.save()
    _db.session.commit()
    return c


def _new_recruiter(label):
    from app.core.security import hash_password
    from app.models.recruiter import Recruiter
    r = Recruiter(
        full_name=f"Recruiter {label}",
        email=f"rec-{label}-{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password(ACCOUNT_PASSWORD),
        company_name=f"Company {label}",
    )
    r.save()
    _db.session.commit()
    return r


def _new_job(recruiter, title):
    from app.models.enums import JobStatus, JobType
    from app.models.job import Job
    j = Job(
        title=title,
        company=recruiter.company_name,
        description="We need an engineer with solid Python and Flask experience.",
        experience_years=3.0,
        location="Remote",
        job_type=JobType.FULL_TIME,
        status=JobStatus.ACTIVE,
        recruiter_id=recruiter.id,
    )
    j.required_skills_list = ["Python", "Flask"]
    j.nice_to_have_skills_list = []
    j.applicant_count = 0
    j.save()
    _db.session.commit()
    return j


def _new_resume(candidate):
    from app.models.enums import ParseStatus
    from app.models.resume import Resume
    r = Resume(
        candidate_id=candidate.id,
        filename="resume.pdf",
        file_path="/tmp/uploads/resume.pdf",
        file_size_kb=100,
        file_type="pdf",
        parse_status=ParseStatus.SUCCESS,
        total_experience_years=4.0,
        is_active=True,
    )
    r.skills_list = ["Python", "Flask"]
    r.save()
    _db.session.commit()
    return r


@pytest.fixture()
def candidate_a(db):
    return _new_candidate("a")


@pytest.fixture()
def candidate_b(db):
    return _new_candidate("b")


@pytest.fixture()
def recruiter_a(db):
    return _new_recruiter("a")


@pytest.fixture()
def recruiter_b(db):
    return _new_recruiter("b")


@pytest.fixture()
def job_a(db, recruiter_a):
    return _new_job(recruiter_a, "Job A")


@pytest.fixture()
def job_b(db, recruiter_b):
    return _new_job(recruiter_b, "Job B")


@pytest.fixture()
def resume_a(db, candidate_a):
    return _new_resume(candidate_a)


@pytest.fixture()
def resume_b(db, candidate_b):
    return _new_resume(candidate_b)


@pytest.fixture()
def application_a(db, candidate_a, resume_a, job_a):
    """Candidate A's application to recruiter A's job A, using résumé A."""
    from app.models.application import Application
    from app.models.enums import ApplicationStage
    a = Application(
        candidate_id=candidate_a.id,
        job_id=job_a.id,
        resume_id=resume_a.id,
        stage=ApplicationStage.APPLIED,
    )
    a.save()
    _db.session.commit()
    return a


@pytest.fixture()
def headers_for(app):
    """headers_for(user) -> {"Authorization": "Bearer <access token>"}."""
    from app.core.security import create_tokens

    def _headers(user):
        role = "recruiter" if type(user).__name__ == "Recruiter" else "candidate"
        with app.app_context():
            access, _refresh, _jti = create_tokens(str(user.id), role)
        return {"Authorization": f"Bearer {access}"}
    return _headers


@pytest.fixture()
def anon():
    """Headers for an unauthenticated request."""
    return {}


@pytest.fixture()
def check_access(client, headers_for, anon):
    """
    check_access(method, url, owner, other, json=None, other_status=403)

    Asserts the three-way access contract for one route:
      no token        -> 401
      another user    -> other_status (403, or 404 for non-active jobs)
      owner           -> 2xx
    The owner is called last, so destructive routes still get the first two
    checks. Returns the owner's response.
    """
    def _check(method, url, owner, other, json=None, other_status=403):
        def call(headers):
            return client.open(url, method=method, json=json, headers=headers)

        r = call(anon)
        assert r.status_code == 401, f"{method} {url} without a token: {r.status_code}"

        r = call(headers_for(other))
        assert r.status_code == other_status, (
            f"{method} {url} as another user: {r.status_code}, expected {other_status}"
        )

        r = call(headers_for(owner))
        assert 200 <= r.status_code < 300, (
            f"{method} {url} as owner: {r.status_code} {r.get_data(as_text=True)[:200]}"
        )
        return r
    return _check


# ─── Service mock ─────────────────────────────────────────────────────────────

@pytest.fixture()
def mock_services(app):
    mock_svcs = MagicMock()
    mock_svcs.groq.available      = False
    mock_svcs.embedding.available = False
    original = app.extensions.get("services")
    app.extensions["services"] = mock_svcs
    yield mock_svcs
    app.extensions["services"] = original


class _UnavailableSemantic:
    """Behaves like SemanticMatcherService when the embedding model is not loaded."""

    def score(self, **kwargs):
        from app.services.semantic_matcher import SemanticScoreResult
        return SemanticScoreResult(score=0.0, raw_cosine=0.0, available=False)


@pytest.fixture()
def ats_scorer(db):
    """
    A real AtsScorerService: real keyword / experience / section-quality
    scorers and AtsScore repository; only the embedding model is stubbed.
    """
    from app.repositories import AtsScoreRepository
    from app.services.ats_scorer import AtsScorerService
    from app.services.experience_scorer import ExperienceScorerService
    from app.services.explainability_engine import ExplainabilityEngine
    from app.services.keyword_matcher import KeywordMatcherService
    from app.services.section_quality_scorer import SectionQualityScorerService

    keyword_matcher = KeywordMatcherService()
    return AtsScorerService(
        keyword_matcher=keyword_matcher,
        semantic_matcher=_UnavailableSemantic(),
        experience_scorer=ExperienceScorerService(),
        section_quality_scorer=SectionQualityScorerService(),
        explainability_engine=ExplainabilityEngine(keyword_matcher=keyword_matcher),
        ats_score_repo=AtsScoreRepository(),
    )


@pytest.fixture()
def resume_file():
    return (io.BytesIO(b"%PDF-1.4 fake pdf content"), "test_resume.pdf")


# ─── Rate limiting ────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _fresh_rate_limit_counters():
    from app.core.extensions import limiter
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture()
def limit(app, monkeypatch):
    """limit("RATE_LIMIT_LLM", "2 per minute"): lower one limit for this test."""
    def _set(name, value):
        monkeypatch.setitem(app.config, name, value)
    return _set
