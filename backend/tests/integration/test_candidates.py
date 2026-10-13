"""
tests/integration/test_candidates.py

Integration tests for /api/v1/candidates/* endpoints.

  GET    /candidates/<id>                — a candidate: self; a recruiter: only applicants to their jobs
  PATCH  /candidates/<id>                — self
  DELETE /candidates/<id>                — self (soft delete)
  GET    /candidates/<id>/resumes        — a candidate: all own; a recruiter: those attached to applications to their jobs
  POST   /candidates/<id>/resumes        — self (file upload)
  GET    /candidates/<id>/skill-gaps     — self
  GET    /candidates/<id>/win-rate-insights — self

There is no candidate-listing route: recruiters reach candidates only through
applications to their own jobs.
"""
import io
from types import SimpleNamespace
from unittest.mock import patch

import pytest

BASE = "/api/v1/candidates"


def _pdf(name="resume.pdf"):
    return {"file": (io.BytesIO(b"%PDF-1.4 minimal pdf content"), name, "application/pdf")}


def _routes(app):
    return {(method, rule.rule) for rule in app.url_map.iter_rules() for method in rule.methods}


class TestRemovedRoutes:
    def test_there_is_no_candidate_listing_route(self, app):
        assert ("GET", f"{BASE}/") not in _routes(app)

    def test_there_is_no_candidate_recommendations_route(self, app):
        assert ("POST", f"{BASE}/<candidate_id>/recommendations") not in _routes(app)


class TestGetCandidate:
    def test_access_rules_for_the_candidate(self, check_access, candidate_a, candidate_b):
        r = check_access("GET", f"{BASE}/{candidate_a.id}", owner=candidate_a, other=candidate_b)
        assert r.get_json()["data"]["id"] == candidate_a.id
        assert isinstance(r.get_json()["data"]["resumes"], list)

    def test_access_rules_for_a_recruiter(
        self, check_access, application_a, candidate_a, recruiter_a, recruiter_b
    ):
        r = check_access("GET", f"{BASE}/{candidate_a.id}", owner=recruiter_a, other=recruiter_b)
        assert r.get_json()["data"]["id"] == candidate_a.id

    def test_recruiter_without_an_application_gets_403(
        self, client, db, candidate_b, recruiter_a, headers_for
    ):
        r = client.get(f"{BASE}/{candidate_b.id}", headers=headers_for(recruiter_a))
        assert r.status_code == 403

    def test_unknown_id_is_403_for_a_recruiter_so_existence_is_not_revealed(
        self, client, db, recruiter_a, headers_for
    ):
        assert client.get(f"{BASE}/no-such-id", headers=headers_for(recruiter_a)).status_code == 403

    def test_recruiter_sees_only_resumes_attached_to_applications_to_their_jobs(
        self, client, db, application_a, candidate_a, resume_a, make_resume, recruiter_a, headers_for
    ):
        extra = make_resume(candidate_id=candidate_a.id)
        db.session.commit()

        as_recruiter = client.get(f"{BASE}/{candidate_a.id}", headers=headers_for(recruiter_a)).get_json()
        as_candidate = client.get(f"{BASE}/{candidate_a.id}", headers=headers_for(candidate_a)).get_json()

        assert [r["id"] for r in as_recruiter["data"]["resumes"]] == [resume_a.id]
        assert {r["id"] for r in as_candidate["data"]["resumes"]} == {resume_a.id, extra.id}

    def test_deleted_candidate_is_404_for_a_recruiter_who_had_an_application(
        self, client, db, application_a, candidate_a, recruiter_a, headers_for
    ):
        candidate_a.soft_delete()
        db.session.commit()
        r = client.get(f"{BASE}/{candidate_a.id}", headers=headers_for(recruiter_a))
        assert r.status_code == 404
        assert r.get_json()["error"]["error_code"] == "CANDIDATE_NOT_FOUND"


class TestUpdateCandidate:
    def test_access_rules(self, check_access, candidate_a, candidate_b):
        r = check_access("PATCH", f"{BASE}/{candidate_a.id}", owner=candidate_a, other=candidate_b,
                         json={"headline": "Updated headline"})
        assert r.get_json()["data"]["headline"] == "Updated headline"

    def test_recruiter_cannot_update(self, client, db, candidate_a, recruiter_a, headers_for):
        r = client.patch(f"{BASE}/{candidate_a.id}", json={"headline": "x"}, headers=headers_for(recruiter_a))
        assert r.status_code == 403

    def test_partial_update_keeps_other_fields(self, client, db, candidate_a, headers_for):
        r = client.patch(f"{BASE}/{candidate_a.id}", json={"headline": "Changed"},
                         headers=headers_for(candidate_a))
        assert r.get_json()["data"]["full_name"] == "Candidate a"

    def test_update_open_to_work(self, client, db, candidate_a, headers_for):
        r = client.patch(f"{BASE}/{candidate_a.id}", json={"open_to_work": False},
                         headers=headers_for(candidate_a))
        assert r.get_json()["data"]["open_to_work"] is False


class TestDeleteCandidate:
    def test_access_rules(self, check_access, candidate_a, candidate_b):
        r = check_access("DELETE", f"{BASE}/{candidate_a.id}", owner=candidate_a, other=candidate_b)
        assert r.status_code == 204

    def test_deleted_candidate_is_gone_for_recruiters(
        self, client, db, application_a, candidate_a, recruiter_a, headers_for
    ):
        client.delete(f"{BASE}/{candidate_a.id}", headers=headers_for(candidate_a))
        assert client.get(f"{BASE}/{candidate_a.id}", headers=headers_for(recruiter_a)).status_code == 404


class TestCandidateResumes:
    def test_access_rules_for_the_candidate(self, check_access, resume_a, candidate_a, candidate_b):
        r = check_access("GET", f"{BASE}/{candidate_a.id}/resumes", owner=candidate_a, other=candidate_b)
        assert [x["id"] for x in r.get_json()["data"]] == [resume_a.id]

    def test_access_rules_for_a_recruiter(
        self, check_access, application_a, candidate_a, recruiter_a, recruiter_b
    ):
        check_access("GET", f"{BASE}/{candidate_a.id}/resumes", owner=recruiter_a, other=recruiter_b)

    def test_recruiter_sees_only_application_linked_resumes(
        self, client, db, application_a, candidate_a, resume_a, make_resume, recruiter_a, headers_for
    ):
        make_resume(candidate_id=candidate_a.id)
        db.session.commit()
        body = client.get(f"{BASE}/{candidate_a.id}/resumes", headers=headers_for(recruiter_a)).get_json()
        assert [r["id"] for r in body["data"]] == [resume_a.id]
        assert body["meta"]["total"] == 1

    def test_candidate_sees_every_own_resume(
        self, client, db, candidate_a, resume_a, make_resume, headers_for
    ):
        extra = make_resume(candidate_id=candidate_a.id)
        db.session.commit()
        body = client.get(f"{BASE}/{candidate_a.id}/resumes", headers=headers_for(candidate_a)).get_json()
        assert {r["id"] for r in body["data"]} == {resume_a.id, extra.id}

    def test_recruiter_without_an_application_gets_403(
        self, client, db, candidate_b, resume_b, recruiter_a, headers_for
    ):
        r = client.get(f"{BASE}/{candidate_b.id}/resumes", headers=headers_for(recruiter_a))
        assert r.status_code == 403


class TestUploadResume:
    @pytest.fixture(autouse=True)
    def _stub_storage_and_parser(self, mock_services):
        stored = SimpleNamespace(key="stub-key", size_kb=1, provider="stub")
        mock_services.resume_parser.parse_bytes.return_value = SimpleNamespace(
            success=False, parse_error="stubbed"
        )
        with patch("app.services.storage_service.LocalStorageBackend.upload", return_value=stored) as upload:
            self.upload = upload
            yield

    def _post(self, client, candidate, headers, data):
        return client.post(f"{BASE}/{candidate.id}/resumes", data=data,
                           content_type="multipart/form-data", headers=headers)

    def test_owner_can_upload(self, client, db, candidate_a, headers_for):
        r = self._post(client, candidate_a, headers_for(candidate_a), _pdf())
        assert r.status_code == 201
        assert r.get_json()["data"]["file_name"] == "resume.pdf"

    def test_storage_gets_the_validated_extension_never_the_filename(self, client, db, candidate_a, headers_for):
        from app.models.resume import Resume
        r = self._post(client, candidate_a, headers_for(candidate_a), _pdf('../../etc/passwd.pdf'))
        assert r.status_code == 201, r.get_json()
        assert self.upload.call_args.kwargs["ext"] == "pdf"
        assert "passwd" not in repr(self.upload.call_args)
        row = db.session.get(Resume, r.get_json()["data"]["id"])
        assert row.storage_key == "stub-key"
        assert row.file_path == row.storage_key

    def test_no_token_401(self, client, db, candidate_a, anon):
        assert self._post(client, candidate_a, anon, _pdf()).status_code == 401
        self.upload.assert_not_called()

    def test_another_candidate_403(self, client, db, candidate_a, candidate_b, headers_for):
        assert self._post(client, candidate_a, headers_for(candidate_b), _pdf()).status_code == 403
        self.upload.assert_not_called()

    def test_recruiter_403(self, client, db, candidate_a, recruiter_a, headers_for):
        assert self._post(client, candidate_a, headers_for(recruiter_a), _pdf()).status_code == 403

    def test_no_file_400(self, client, db, candidate_a, headers_for):
        r = self._post(client, candidate_a, headers_for(candidate_a), {})
        assert r.status_code == 400
        assert r.get_json()["error"]["error_code"] == "NO_FILE_UPLOADED"

    def test_unsupported_type_415(self, client, db, candidate_a, headers_for):
        data = {"file": (io.BytesIO(b"plain text content"), "resume.txt", "text/plain")}
        assert self._post(client, candidate_a, headers_for(candidate_a), data).status_code == 415


class TestCandidateInsights:
    def test_skill_gaps_access_rules(self, check_access, candidate_a, candidate_b):
        check_access("GET", f"{BASE}/{candidate_a.id}/skill-gaps", owner=candidate_a, other=candidate_b)

    def test_win_rate_insights_access_rules(self, check_access, candidate_a, candidate_b):
        check_access("GET", f"{BASE}/{candidate_a.id}/win-rate-insights", owner=candidate_a, other=candidate_b)
