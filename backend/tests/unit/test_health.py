
"""
tests/integration/test_health.py

Integration tests for health check endpoints.
"""

import json


def test_liveness_returns_200(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["data"]["status"] == "ok"
    assert "timestamp" in body["data"]
    assert "version" in body["data"]


def test_readiness_returns_200_with_db(client):
    resp = client.get("/api/v1/health/ready")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["data"]["checks"]["database"] == "ok"


def test_liveness_response_headers(client):
    resp = client.get("/api/v1/health")
    assert "X-Request-ID" in resp.headers


def test_404_returns_json(client):
    resp = client.get("/api/v1/nonexistent-route")
    assert resp.status_code == 404
    body = resp.get_json()
    assert body["success"] is False
    assert body["error"]["error_code"] == "NOT_FOUND"


def test_405_returns_json(client):
    """DELETE on a GET-only endpoint should return JSON 405."""
    resp = client.delete("/api/v1/health")
    assert resp.status_code == 405
    body = resp.get_json()
    assert body["success"] is False


def test_stub_candidates_endpoint(client):
    resp = client.get("/api/v1/candidates/")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True


def test_stub_jobs_endpoint(client):
    resp = client.get("/api/v1/jobs/")
    assert resp.status_code == 200