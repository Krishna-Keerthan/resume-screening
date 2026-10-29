"""
How many SQL statements a request issues. The numbers are the minimum the endpoint needs:
a change that adds a query has to change a number here and say why.
"""
import pytest
from sqlalchemy import event

from app.repositories.resume import ResumeRepository


@pytest.fixture()
def statements(db):
    seen = []

    def record(conn, cursor, statement, parameters, context, executemany):
        text = " ".join(statement.split())
        if not text.startswith(("SAVEPOINT", "RELEASE SAVEPOINT", "ROLLBACK TO SAVEPOINT")):
            seen.append(text)

    event.listen(db.engine, "before_cursor_execute", record)
    yield seen
    event.remove(db.engine, "before_cursor_execute", record)


def _selects_from(statements, table):
    return [s for s in statements if s.startswith("SELECT") and f"FROM {table}" in s]


def test_a_candidate_reading_their_own_profile_loads_the_candidate_once(
        client, db, candidate_a, resume_a, headers_for, statements):
    headers, candidate_id = headers_for(candidate_a), candidate_a.id
    db.session.commit()
    db.session.expire_all()
    statements.clear()

    response = client.get(f"/api/v1/candidates/{candidate_id}", headers=headers)

    assert response.status_code == 200
    assert len(_selects_from(statements, "candidates")) == 1
    assert len(statements) == 2           # the candidate, and their résumés (the page is not full)


def test_a_recruiter_reading_an_applicant_issues_four_statements(
        client, db, candidate_a, recruiter_a, application_a, headers_for, statements):
    headers, candidate_id = headers_for(recruiter_a), candidate_a.id
    db.session.commit()
    db.session.expire_all()
    statements.clear()

    response = client.get(f"/api/v1/candidates/{candidate_id}", headers=headers)

    assert response.status_code == 200
    assert len(statements) == 4           # recruiter, applied-to-me check, candidate, résumés


class TestResumePages:
    def _three_resumes(self, make_resume, candidate_a):
        for _ in range(3):
            make_resume(candidate_a.id)

    def test_a_page_that_is_not_full_needs_no_count(self, db, candidate_a, make_resume, statements):
        self._three_resumes(make_resume, candidate_a)
        statements.clear()

        items, total = ResumeRepository().list_by_candidate(candidate_a.id, limit=10)

        assert (len(items), total) == (3, 3)
        assert not [s for s in statements if "count(*)" in s.lower()]

    def test_a_full_page_still_counts(self, db, candidate_a, make_resume, statements):
        self._three_resumes(make_resume, candidate_a)
        statements.clear()

        items, total = ResumeRepository().list_by_candidate(candidate_a.id, limit=2)

        assert (len(items), total) == (2, 3)
        assert [s for s in statements if "count(*)" in s.lower()]

    def test_a_page_past_the_end_still_counts(self, db, candidate_a, make_resume, statements):
        self._three_resumes(make_resume, candidate_a)

        items, total = ResumeRepository().list_by_candidate(candidate_a.id, page=3, limit=2)

        assert (items, total) == ([], 3)

    def test_the_last_page_total_is_the_offset_plus_what_it_holds(self, db, candidate_a, make_resume):
        self._three_resumes(make_resume, candidate_a)

        items, total = ResumeRepository().list_by_candidate(candidate_a.id, page=2, limit=2)

        assert (len(items), total) == (1, 3)

    def test_an_empty_first_page_is_a_total_of_zero_without_a_count(self, db, candidate_a, statements):
        statements.clear()

        assert ResumeRepository().list_by_candidate(candidate_a.id) == ([], 0)
        assert not [s for s in statements if "count(*)" in s.lower()]
