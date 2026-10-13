"""
tests/unit/test_repository_search.py  —  search / location filters treat
% and _ literally instead of as LIKE wildcards.
"""


def _job(recruiter_id, title, location="Remote"):
    from app.models.enums import JobStatus, JobType
    from app.models.job import Job
    job = Job(
        title=title,
        company="TechCorp Pvt Ltd",
        description="A job description long enough to be a realistic posting body.",
        experience_years=1.0,
        location=location,
        job_type=JobType.FULL_TIME,
        status=JobStatus.ACTIVE,
        recruiter_id=recruiter_id,
    )
    job.save()
    return job


class TestJobSearch:
    def _titles(self, **filters):
        from app.repositories import JobRepository
        items, _ = JobRepository().list_all(**filters)
        return {j.title for j in items}

    def test_search_is_case_insensitive(self, db, sample_recruiter):
        _job(sample_recruiter.id, "Senior Python Developer")
        assert self._titles(search="python") == {"Senior Python Developer"}

    def test_search_percent_is_literal(self, db, sample_recruiter):
        _job(sample_recruiter.id, "100% Remote Engineer")
        _job(sample_recruiter.id, "1000 Hours Engineer")
        assert self._titles(search="100%") == {"100% Remote Engineer"}

    def test_location_underscore_is_literal(self, db, sample_recruiter):
        _job(sample_recruiter.id, "Engineer A", location="Site_7")
        _job(sample_recruiter.id, "Engineer B", location="Site-7")
        assert self._titles(location="site_7") == {"Engineer A"}


class TestFindDuplicates:
    def _titles(self, recruiter_id, title, company):
        from app.repositories import JobRepository
        return {j.title for j in JobRepository().find_duplicates(title, company, recruiter_id)}

    def test_title_match_is_case_insensitive_substring(self, db, sample_recruiter):
        _job(sample_recruiter.id, "Senior Python Developer")
        assert self._titles(sample_recruiter.id, "python developer", "techcorp pvt ltd") == {
            "Senior Python Developer"
        }

    def test_title_percent_is_literal(self, db, sample_recruiter):
        _job(sample_recruiter.id, "100% Remote Engineer")
        _job(sample_recruiter.id, "1000 Hours Engineer")
        assert self._titles(sample_recruiter.id, "100%", "TechCorp Pvt Ltd") == {
            "100% Remote Engineer"
        }

    def test_company_must_match_exactly_without_wildcards(self, db, sample_recruiter):
        _job(sample_recruiter.id, "Engineer")
        assert self._titles(sample_recruiter.id, "Engineer", "TechCorp_Pvt Ltd") == set()
        assert self._titles(sample_recruiter.id, "Engineer", "TechCorp") == set()
