"""tests/integration/test_health.py — Health endpoint integration tests."""
from types import SimpleNamespace

import pytest

from app.services.storage_service import SupabaseStorageBackend
from tests.unit.fake_supabase import BUCKET, SERVICE_KEY, URL, FakeSupabase


class TestLiveness:
    def test_returns_200(self, client):
        assert client.get("/api/v1/health").status_code == 200

    def test_success_envelope(self, client):
        body = client.get("/api/v1/health").get_json()
        assert body["success"] is True

    def test_status_ok(self, client):
        body = client.get("/api/v1/health").get_json()
        assert body["data"]["status"] == "ok"

    def test_uptime_seconds_present(self, client):
        body = client.get("/api/v1/health").get_json()
        assert "uptime_seconds" in body["data"]
        assert isinstance(body["data"]["uptime_seconds"], (int, float))
        assert body["data"]["uptime_seconds"] >= 0


class TestReadiness:
    def test_returns_200(self, client):
        assert client.get("/api/v1/health/ready").status_code == 200

    def test_database_check_ok(self, client):
        body = client.get("/api/v1/health/ready").get_json()
        assert body["data"]["checks"]["database"]["status"] == "ok"

    def test_success_true(self, client):
        body = client.get("/api/v1/health/ready").get_json()
        assert body["success"] is True

    def test_services_check_present(self, client):
        body = client.get("/api/v1/health/ready").get_json()
        assert "services" in body["data"]["checks"]


class TestServiceStatus:
    def test_returns_200(self, client):
        assert client.get("/api/v1/health/services").status_code == 200

    def test_reports_availability_for_database_search_and_ai(self, client):
        svcs = client.get("/api/v1/health/services").get_json()["data"]["services"]
        assert set(svcs) == {"database", "semantic_search", "ai_assistance"}

    def test_every_service_value_is_a_bare_boolean(self, client):
        data = client.get("/api/v1/health/services").get_json()["data"]
        assert all(isinstance(v, bool) for v in data["services"].values())
        assert isinstance(data["all_optional_services_available"], bool)

    def test_database_available_true(self, client):
        assert client.get("/api/v1/health/services").get_json()["data"]["services"]["database"] is True

    def test_availability_follows_the_service_container(self, client, mock_services):
        mock_services.embedding.available = True
        mock_services.groq.available = False
        data = client.get("/api/v1/health/services").get_json()["data"]
        assert data["services"]["semantic_search"] is True
        assert data["services"]["ai_assistance"] is False
        assert data["all_optional_services_available"] is False

    def test_response_names_no_component_or_version(self, client):
        text = client.get("/api/v1/health/services").get_data(as_text=True).lower()
        for word in ("groq", "llama", "minilm", "sentence", "transformers", "postgres", "sqlite"):
            assert word not in text


class TestErrorHandlers:
    def test_404_returns_json(self, client):
        r = client.get("/api/v1/nonexistent-route-xyz-abc")
        assert r.status_code == 404
        body = r.get_json()
        assert body["success"] is False
        assert body["error"]["error_code"] == "NOT_FOUND"

    def test_405_returns_json(self, client):
        r = client.patch("/api/v1/health")
        assert r.status_code == 405
        body = r.get_json()
        assert body["success"] is False

    def test_404_error_envelope_shape(self, client):
        body = client.get("/api/v1/this-does-not-exist").get_json()
        assert "error" in body
        assert "error_code" in body["error"]
        assert "message" in body["error"]

class TestReadinessFailure:
    SECRET = "postgresql://admin:hunter2@db.internal:5432/ats"

    def test_database_failure_is_reported_without_the_exception_text(self, client):
        from unittest.mock import patch

        from app.core.database import db

        with patch.object(db.session, "execute", side_effect=RuntimeError(self.SECRET)):
            resp = client.get("/api/v1/health/ready")

        assert resp.status_code == 503
        assert "hunter2" not in resp.get_data(as_text=True)
        assert resp.get_json()["error"]["details"]["checks"]["database"]["status"] == "error"


class TestReadinessStorage:
    @pytest.fixture()
    def supabase(self, app, monkeypatch):
        fake = FakeSupabase()
        backend = SupabaseStorageBackend(URL, SERVICE_KEY, BUCKET, transport=fake.transport)
        monkeypatch.setitem(app.extensions, "services", SimpleNamespace(storage=backend))
        return fake

    def _ready(self, client):
        resp = client.get("/api/v1/health/ready")
        return resp, resp.get_json()

    def test_reachable_storage_is_reported_true(self, client, supabase):
        resp, body = self._ready(client)

        assert resp.status_code == 200
        assert body["data"]["checks"]["storage"] == {"reachable": True}

    def test_a_wrong_key_is_reported_false_without_failing_readiness(self, client, supabase):
        supabase.service_key = "sb_secret_rotated"

        resp, body = self._ready(client)

        assert resp.status_code == 200
        assert body["data"]["checks"]["storage"] == {"reachable": False}

    def test_a_missing_bucket_is_reported_false(self, client, supabase):
        supabase.bucket = "other-bucket"

        _, body = self._ready(client)

        assert body["data"]["checks"]["storage"] == {"reachable": False}

    def test_the_response_names_no_url_bucket_or_key(self, client, supabase):
        supabase.service_key = "sb_secret_rotated"

        text = client.get("/api/v1/health/ready").get_data(as_text=True)

        for secret in (URL, "supabase.co", BUCKET, SERVICE_KEY, "sb_secret"):
            assert secret not in text
