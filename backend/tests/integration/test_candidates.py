"""
tests/integration/test_candidates.py

Integration tests for /api/v1/candidates/* endpoints.

Coverage:
  GET  /candidates/               — list with pagination_meta + filters
  POST /candidates/               — create, duplicate email, validation
  GET  /candidates/<id>           — retrieve + embedded resumes
  PATCH /candidates/<id>          — partial update
  DELETE /candidates/<id>         — soft-delete (status_code == 204)
  GET  /candidates/<id>/resumes   — list resumes for candidate
  POST /candidates/<id>/resumes   — file upload (PDF / DOCX / invalid type)
"""
import io
import uuid

import pytest

BASE = "/api/v1/candidates"


def _payload(**overrides):
    base = {
        "full_name": "Test Candidate",
        "email": f"test_{uuid.uuid4().hex[:8]}@example.com",
        "location": "Bangalore, India",
        "headline": "Python Developer",
        "open_to_work": True,
        "preferred_roles": ["Backend Engineer"],
    }
    base.update(overrides)
    return base


# ── List ──────────────────────────────────────────────────────────────────────

class TestListCandidates:
    def test_returns_200(self, client, db):
        r = client.get(f"{BASE}/")
        assert r.status_code == 200

    def test_success_envelope(self, client, db):
        body = client.get(f"{BASE}/").get_json()
        assert body["success"] is True

    def test_data_is_list(self, client, db):
        body = client.get(f"{BASE}/").get_json()
        assert isinstance(body["data"], list)

    def test_has_pagination_meta(self, client, db):
        body = client.get(f"{BASE}/").get_json()
        meta = body["meta"]
        assert "total" in meta
        assert "page" in meta
        assert "limit" in meta
        assert "total_pages" in meta

    def test_custom_page_and_limit(self, client, db):
        body = client.get(f"{BASE}/?page=1&limit=5").get_json()
        assert body["meta"]["page"] == 1
        assert body["meta"]["limit"] == 5

    def test_open_to_work_filter(self, client, db, make_candidate):
        make_candidate(open_to_work=True)
        body = client.get(f"{BASE}/?open_to_work=true").get_json()
        assert all(c["open_to_work"] is True for c in body["data"])

    def test_search_filter(self, client, db, make_candidate):
        make_candidate(full_name="UniqueSearchCandidate")
        body = client.get(f"{BASE}/?search=UniqueSearchCandidate").get_json()
        found = [x for x in body["data"] if x["full_name"] == "UniqueSearchCandidate"]
        assert len(found) >= 1


# ── Create ────────────────────────────────────────────────────────────────────

class TestCreateCandidate:
    def test_returns_201(self, client, db, api_post):
        r, body = api_post(f"{BASE}/", _payload())
        assert r.status_code == 201

    def test_success_true(self, client, db, api_post):
        _, body = api_post(f"{BASE}/", _payload())
        assert body["success"] is True

    def test_returns_id(self, client, db, api_post):
        _, body = api_post(f"{BASE}/", _payload())
        assert body["data"]["id"] is not None

    def test_fields_persisted(self, client, db, api_post):
        payload = _payload()
        _, body = api_post(f"{BASE}/", payload)
        assert body["data"]["full_name"] == payload["full_name"]
        assert body["data"]["location"] == payload["location"]

    def test_missing_email_400(self, client, db, api_post):
        payload = _payload()
        del payload["email"]
        r, body = api_post(f"{BASE}/", payload)
        assert r.status_code == 400

    def test_missing_full_name_400(self, client, db, api_post):
        payload = _payload()
        del payload["full_name"]
        r, body = api_post(f"{BASE}/", payload)
        assert r.status_code == 400

    def test_invalid_email_returns_400(self, client, db, api_post):
        r, body = api_post(f"{BASE}/", _payload(email="not-valid"))
        assert r.status_code == 400

    def test_duplicate_email_returns_409(self, client, db, api_post, make_candidate):
        c = make_candidate()
        r, body = api_post(f"{BASE}/", _payload(email=c.email))
        assert r.status_code == 409
        assert body["error"]["error_code"] == "CANDIDATE_EMAIL_CONFLICT"

    def test_preferred_roles_saved(self, client, db, api_post):
        payload = _payload(preferred_roles=["Data Engineer", "ML Ops"])
        _, body = api_post(f"{BASE}/", payload)
        assert "Data Engineer" in body["data"]["preferred_roles"]

    def test_open_to_work_true_by_default(self, client, db, api_post):
        payload = _payload()
        payload.pop("open_to_work", None)
        _, body = api_post(f"{BASE}/", payload)
        assert body["data"]["open_to_work"] is True


# ── Get single ────────────────────────────────────────────────────────────────

class TestGetCandidate:
    def test_returns_200(self, client, db, make_candidate):
        c = make_candidate()
        r = client.get(f"{BASE}/{c.id}")
        assert r.status_code == 200

    def test_correct_data(self, client, db, make_candidate):
        c = make_candidate()
        body = client.get(f"{BASE}/{c.id}").get_json()
        assert body["data"]["id"] == c.id
        assert body["data"]["full_name"] == c.full_name

    def test_includes_resumes_key(self, client, db, make_candidate):
        c = make_candidate()
        body = client.get(f"{BASE}/{c.id}").get_json()
        assert "resumes" in body["data"]
        assert isinstance(body["data"]["resumes"], list)

    def test_nonexistent_returns_404(self, client, db):
        r = client.get(f"{BASE}/does-not-exist-xyz")
        assert r.status_code == 404

    def test_not_found_error_code(self, client, db):
        body = client.get(f"{BASE}/no-such-id").get_json()
        assert body["error"]["error_code"] == "CANDIDATE_NOT_FOUND"


# ── Update ────────────────────────────────────────────────────────────────────

class TestUpdateCandidate:
    def test_returns_200(self, client, db, make_candidate, api_patch):
        c = make_candidate()
        r, _ = api_patch(f"{BASE}/{c.id}", {"headline": "Updated headline"})
        assert r.status_code == 200

    def test_field_updated(self, client, db, make_candidate, api_patch):
        c = make_candidate()
        _, body = api_patch(f"{BASE}/{c.id}", {"headline": "New headline text"})
        assert body["data"]["headline"] == "New headline text"

    def test_partial_update_keeps_other_fields(self, client, db, make_candidate, api_patch):
        c = make_candidate(full_name="Stay Same")
        _, body = api_patch(f"{BASE}/{c.id}", {"headline": "Changed"})
        assert body["data"]["full_name"] == "Stay Same"

    def test_update_open_to_work(self, client, db, make_candidate, api_patch):
        c = make_candidate(open_to_work=True)
        _, body = api_patch(f"{BASE}/{c.id}", {"open_to_work": False})
        assert body["data"]["open_to_work"] is False

    def test_nonexistent_returns_404(self, client, db, api_patch):
        r, _ = api_patch(f"{BASE}/ghost-id", {"headline": "hi"})
        assert r.status_code == 404


# ── Delete ────────────────────────────────────────────────────────────────────

class TestDeleteCandidate:
    def test_soft_delete_returns_204(self, client, db, make_candidate):
        c = make_candidate()
        r = client.delete(f"{BASE}/{c.id}")
        assert r.status_code == 204

    def test_returns_204(self, client, db, make_candidate):
        c = make_candidate()
        r = client.delete(f"{BASE}/{c.id}")
        assert r.status_code == 204

    def test_deleted_not_returned_in_list(self, client, db, make_candidate):
        c = make_candidate()
        client.delete(f"{BASE}/{c.id}")
        body = client.get(f"{BASE}/").get_json()
        ids = [x["id"] for x in body["data"]]
        assert c.id not in ids

    def test_deleted_candidate_returns_404_on_get(self, client, db, make_candidate):
        c = make_candidate()
        client.delete(f"{BASE}/{c.id}")
        r = client.get(f"{BASE}/{c.id}")
        assert r.status_code == 404

    def test_nonexistent_returns_404(self, client, db):
        r = client.delete(f"{BASE}/phantom-id")
        assert r.status_code == 404


# ── Resume sub-resource ───────────────────────────────────────────────────────

class TestCandidateResumes:
    def test_list_resumes_returns_200(self, client, db, make_candidate):
        c = make_candidate()
        r = client.get(f"{BASE}/{c.id}/resumes")
        assert r.status_code == 200

    def test_list_resumes_data_is_list(self, client, db, make_candidate):
        c = make_candidate()
        body = client.get(f"{BASE}/{c.id}/resumes").get_json()
        assert isinstance(body["data"], list)

    def test_list_resumes_includes_created(self, client, db, make_candidate, make_resume):
        c = make_candidate()
        res = make_resume(candidate_id=c.id)
        body = client.get(f"{BASE}/{c.id}/resumes").get_json()
        assert any(r["id"] == res.id for r in body["data"])

    def test_upload_no_file_returns_400(self, client, db, make_candidate):
        c = make_candidate()
        r = client.post(
            f"{BASE}/{c.id}/resumes",
            data={},
            content_type="multipart/form-data",
        )
        assert r.status_code == 400
        body = r.get_json()
        assert body["error"]["error_code"] == "NO_FILE_UPLOADED"

    def test_upload_unsupported_type_returns_415(self, client, db, make_candidate):
        c = make_candidate()
        data = {"file": (io.BytesIO(b"plain text content"), "resume.txt", "text/plain")}
        r = client.post(
            f"{BASE}/{c.id}/resumes",
            data=data,
            content_type="multipart/form-data",
        )
        assert r.status_code == 415
        body = r.get_json()
        assert body["error"]["error_code"] == "UNSUPPORTED_FILE_TYPE"

    def test_upload_nonexistent_candidate_returns_404(self, client, db):
        data = {"file": (io.BytesIO(b"%PDF-1.4 test"), "resume.pdf", "application/pdf")}
        r = client.post(
            f"{BASE}/no-such-candidate/resumes",
            data=data,
            content_type="multipart/form-data",
        )
        assert r.status_code == 404

    def test_upload_valid_pdf_creates_record(self, client, db, make_candidate):
        c = make_candidate()
        data = {"file": (io.BytesIO(b"%PDF-1.4 minimal pdf content"), "resume.pdf", "application/pdf")}
        r = client.post(
            f"{BASE}/{c.id}/resumes",
            data=data,
            content_type="multipart/form-data",
        )
        assert r.status_code == 201
        body = r.get_json()
        assert body["data"]["id"] is not None
        assert body["data"]["filename"] == "resume.pdf"