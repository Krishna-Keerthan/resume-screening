"""
/api/v1/health/services must answer 200 with database:false when the database is the
problem. It checks the database on its own short-lived connection, not the request's ORM
session, and reuses the answer for DATABASE_HEALTH_CACHE_SECONDS.
"""
from unittest.mock import patch

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from app.utils.cached_probe import CachedProbe
from config.settings import BaseConfig, DevelopmentConfig, ProductionConfig, TestingConfig

_URL = "/api/v1/health/services"


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_an_unreachable_database_gives_200_and_database_false(client, db):
    down = OperationalError("SELECT 1", {}, Exception("connection refused"))
    with patch.object(Engine, "connect", side_effect=down):
        response = client.get(_URL)

    assert response.status_code == 200
    body = response.get_json()
    assert body["data"]["services"]["database"] is False
    assert "connection refused" not in response.get_data(as_text=True)


def test_the_database_answer_is_reused_until_the_ttl_has_passed(app, client):
    clock, checks = _Clock(), []
    probe = CachedProbe(lambda: checks.append(1) or True, 10, clock=clock)
    with patch.dict(app.extensions, {"database_probe": probe}):
        client.get(_URL)
        client.get(_URL)
        clock.now += 9
        client.get(_URL)
        assert len(checks) == 1        # still inside the TTL

        clock.now += 2
        client.get(_URL)
        assert len(checks) == 2        # expired: one new check


def test_a_cached_failure_is_reported_until_the_ttl_has_passed(app, client):
    clock, database_is_up = _Clock(), [False]
    probe = CachedProbe(lambda: database_is_up[0], 10, clock=clock)
    with patch.dict(app.extensions, {"database_probe": probe}):
        assert client.get(_URL).get_json()["data"]["services"]["database"] is False
        database_is_up[0] = True
        clock.now += 5
        assert client.get(_URL).get_json()["data"]["services"]["database"] is False   # cached
        clock.now += 6
        assert client.get(_URL).get_json()["data"]["services"]["database"] is True    # re-checked


def test_the_ttl_is_a_setting_with_no_caching_in_tests():
    assert BaseConfig.DATABASE_HEALTH_CACHE_SECONDS == 10
    assert DevelopmentConfig.DATABASE_HEALTH_CACHE_SECONDS == 10
    assert ProductionConfig.DATABASE_HEALTH_CACHE_SECONDS == 10
    assert TestingConfig.DATABASE_HEALTH_CACHE_SECONDS == 0


@pytest.mark.parametrize("url", [_URL, "/api/v1/health", "/api/v1/health/ready"])
def test_head_is_answered_without_a_body(client, url):
    response = client.head(url)

    assert response.status_code == 200
    assert response.get_data() == b""
