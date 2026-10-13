"""
tests/integration/test_recruiters.py

Integration tests for /api/v1/recruiters/* endpoints. Every route is
self-only: a recruiter can read and change only their own account.
"""
from types import SimpleNamespace

BASE = "/api/v1/recruiters"


def _routes(app):
    return {(method, rule.rule) for rule in app.url_map.iter_rules() for method in rule.methods}


class TestRemovedRoutes:
    def test_there_is_no_recruiter_listing_route(self, app):
        assert ("GET", f"{BASE}/") not in _routes(app)

    def test_there_is_no_recruiter_pipeline_route(self, app):
        assert ("GET", f"{BASE}/<recruiter_id>/pipeline") not in _routes(app)


class TestGetRecruiter:
    def test_access_rules(self, check_access, recruiter_a, recruiter_b):
        r = check_access("GET", f"{BASE}/{recruiter_a.id}", owner=recruiter_a, other=recruiter_b)
        assert r.get_json()["data"]["id"] == recruiter_a.id
        assert r.get_json()["data"]["company_name"] == recruiter_a.company_name

    def test_a_candidate_gets_403(self, client, db, recruiter_a, candidate_a, headers_for):
        r = client.get(f"{BASE}/{recruiter_a.id}", headers=headers_for(candidate_a))
        assert r.status_code == 403


class TestUpdateRecruiter:
    def test_access_rules(self, check_access, recruiter_a, recruiter_b):
        r = check_access("PATCH", f"{BASE}/{recruiter_a.id}", owner=recruiter_a, other=recruiter_b,
                         json={"industry": "Fintech"})
        assert r.get_json()["data"]["industry"] == "Fintech"

    def test_partial_update_keeps_other_fields(self, client, db, recruiter_a, headers_for):
        r = client.patch(f"{BASE}/{recruiter_a.id}", json={"industry": "Healthcare"},
                         headers=headers_for(recruiter_a))
        assert r.get_json()["data"]["full_name"] == "Recruiter a"

    def test_another_recruiter_changes_nothing(self, client, db, recruiter_a, recruiter_b, headers_for):
        client.patch(f"{BASE}/{recruiter_a.id}", json={"industry": "Hijacked"},
                     headers=headers_for(recruiter_b))
        db.session.refresh(recruiter_a)
        assert recruiter_a.industry != "Hijacked"


class TestDeleteRecruiter:
    def test_access_rules(self, check_access, recruiter_a, recruiter_b):
        r = check_access("DELETE", f"{BASE}/{recruiter_a.id}", owner=recruiter_a, other=recruiter_b)
        assert r.status_code == 204

    def test_another_recruiter_cannot_delete(self, client, db, recruiter_a, recruiter_b, headers_for):
        client.delete(f"{BASE}/{recruiter_a.id}", headers=headers_for(recruiter_b))
        db.session.refresh(recruiter_a)
        assert recruiter_a.is_deleted is False


class TestRecruiterJobs:
    def test_access_rules(self, check_access, job_a, recruiter_a, recruiter_b):
        r = check_access("GET", f"{BASE}/{recruiter_a.id}/jobs", owner=recruiter_a, other=recruiter_b)
        assert [j["id"] for j in r.get_json()["data"]] == [job_a.id]

    def test_filter_by_status(self, client, db, job_a, recruiter_a, headers_for):
        active = client.get(f"{BASE}/{recruiter_a.id}/jobs?status=active", headers=headers_for(recruiter_a))
        closed = client.get(f"{BASE}/{recruiter_a.id}/jobs?status=closed", headers=headers_for(recruiter_a))
        assert [j["id"] for j in active.get_json()["data"]] == [job_a.id]
        assert closed.get_json()["data"] == []


class TestRecruiterAnalytics:
    def test_access_rules(self, check_access, recruiter_a, recruiter_b, mock_services):
        mock_services.recruiter_analytics.get_dashboard.return_value = SimpleNamespace(
            recruiter_id=recruiter_a.id, total_jobs=0)
        r = check_access("GET", f"{BASE}/{recruiter_a.id}/analytics", owner=recruiter_a, other=recruiter_b)
        assert r.get_json()["data"]["total_jobs"] == 0
