"""tests/integration/test_health.py — Health endpoint integration tests."""


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

    def test_has_all_three_services(self, client):
        body = client.get("/api/v1/health/services").get_json()
        svcs = body["data"]["services"]
        assert "database" in svcs
        assert "embedding" in svcs
        assert "groq" in svcs

    def test_database_available_true(self, client):
        body = client.get("/api/v1/health/services").get_json()
        assert body["data"]["services"]["database"]["available"] is True

    def test_each_service_has_available_and_description(self, client):
        body = client.get("/api/v1/health/services").get_json()
        for svc in body["data"]["services"].values():
            assert "available" in svc
            assert "description" in svc


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