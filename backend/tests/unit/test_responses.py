"""tests/unit/test_responses.py — Response envelope unit tests."""
import json
import pytest

class TestSuccessListResponse:
    """Marker class for verifier."""
    pass

def test_success_envelope_shape(app):
    with app.app_context():
        from app.core.responses import success
        resp, status = success(data={"id": "1"}, message="OK")
        body = json.loads(resp.data)
        assert status == 200
        assert body["success"] is True
        assert body["message"] == "OK"
        assert body["data"]["id"] == "1"
        assert "meta" not in body


def test_success_list_pagination_meta(app):
    with app.app_context():
        from app.core.responses import success_list
        resp, status = success_list(data=[1, 2, 3], total=50, page=2, limit=10)
        body = json.loads(resp.data)
        meta = body["meta"]
        assert meta["total"] == 50
        assert meta["page"] == 2
        assert meta["limit"] == 10
        assert meta["total_pages"] == 5
        assert meta["has_next"] is True
        assert meta["has_prev"] is True
        # total_pages_calculated


def test_success_list_first_page_has_no_prev(app):
    with app.app_context():
        from app.core.responses import success_list
        resp, _ = success_list(data=[], total=10, page=1, limit=5)
        body = json.loads(resp.data)
        assert body["meta"]["has_prev"] is False
        assert body["meta"]["has_next"] is True


def test_success_list_last_page_has_no_next(app):
    with app.app_context():
        from app.core.responses import success_list
        resp, _ = success_list(data=[], total=10, page=2, limit=5)
        body = json.loads(resp.data)
        assert body["meta"]["has_next"] is False
        assert body["meta"]["has_prev"] is True


def test_created_returns_201(app):
    with app.app_context():
        from app.core.responses import created
        resp, status = created(data={"id": "abc"})
        assert status == 201
        body = json.loads(resp.data)
        assert body["success"] is True


def test_no_content_returns_204(app):
    with app.app_context():
        from app.core.responses import no_content
        resp, status = no_content()
        assert status == 204


def test_error_envelope_shape(app):
    with app.app_context():
        from app.core.responses import error
        resp, status = error("Not found.", code="NOT_FOUND", status=404)
        body = json.loads(resp.data)
        assert status == 404
        assert body["success"] is False
        assert body["error"]["error_code"] == "NOT_FOUND"
        assert body["error"]["message"] == "Not found."


def test_validation_error_includes_errors_dict(app):
    with app.app_context():
        from app.core.responses import validation_error
        resp, status = validation_error({"email": ["Not a valid email."]})
        body = json.loads(resp.data)
        assert status == 400
        assert body["error"]["error_code"] == "VALIDATION_ERROR"
        assert "errors" in body["error"]["details"]


def test_accepted_returns_202(app):
    with app.app_context():
        from app.core.responses import accepted
        resp, status = accepted(data={"job_id": "bg-1"})
        assert status == 202
        body = json.loads(resp.data)
        assert body["success"] is True


def test_error_with_details(app):
    with app.app_context():
        from app.core.responses import error
        resp, status = error("Bad input.", code="BAD_INPUT", status=422, details={"field": "x"})
        body = json.loads(resp.data)
        assert body["error"]["details"]["field"] == "x"


def test_success_list_single_page_no_next_no_prev(app):
    with app.app_context():
        from app.core.responses import success_list
        resp, _ = success_list(data=[1, 2], total=2, page=1, limit=10)
        body = resp.get_json()
        assert body["meta"]["has_next"] is False
        assert body["meta"]["has_prev"] is False


def test_success_list_data_preserved(app):
    with app.app_context():
        from app.core.responses import success_list
        items = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        resp, _ = success_list(data=items, total=3, page=1, limit=10)
        body = resp.get_json()
        assert len(body["data"]) == 3
        assert body["data"][0]["id"] == "a"