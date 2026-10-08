"""
tests/unit/test_mixins.py  —  SoftDeleteMixin / SearchableMixin.
"""


def _job(recruiter_id, title):
    from app.models.enums import JobStatus, JobType
    from app.models.job import Job
    job = Job(
        title=title,
        company="TechCorp Pvt Ltd",
        description="A job description long enough to be a realistic posting body.",
        experience_years=1.0,
        location="Remote",
        job_type=JobType.FULL_TIME,
        status=JobStatus.ACTIVE,
        recruiter_id=recruiter_id,
    )
    job.save()
    return job


class TestSearchFilter:
    def _titles(self, db, term):
        from app.models.job import Job
        query = Job.search_filter(db.session.query(Job), term, [Job.title])
        return {j.title for j in query}

    def test_matches_case_insensitively(self, db, sample_recruiter):
        _job(sample_recruiter.id, "Senior Python Developer")
        assert self._titles(db, "python") == {"Senior Python Developer"}

    def test_percent_in_term_is_literal(self, db, sample_recruiter):
        _job(sample_recruiter.id, "100% Remote Engineer")
        _job(sample_recruiter.id, "1000 Hours Engineer")
        assert self._titles(db, "100%") == {"100% Remote Engineer"}

    def test_underscore_in_term_is_literal(self, db, sample_recruiter):
        _job(sample_recruiter.id, "C_Sharp Engineer")
        _job(sample_recruiter.id, "CxSharp Engineer")
        assert self._titles(db, "C_Sharp") == {"C_Sharp Engineer"}


def test_soft_delete_mixin_precedes_base_model():
    # SoftDeleteMixin.to_dict() must run before BaseModel.to_dict(), or
    # deleted_at silently disappears from serialised output.
    from app.core.database import BaseModel
    from app.models.mixins import SoftDeleteMixin

    soft_deletable = [
        m.class_ for m in BaseModel.registry.mappers
        if issubclass(m.class_, SoftDeleteMixin)
    ]
    assert soft_deletable
    for model in soft_deletable:
        mro = model.__mro__
        assert mro.index(SoftDeleteMixin) < mro.index(BaseModel), model.__name__
