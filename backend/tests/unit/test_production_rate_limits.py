"""
The production app runs the rate limiter with the real login limits, not the test ones.

The test config sets every limit to a million per minute so the limiter is enabled but
never trips. Here the app boots with the production config in a fresh interpreter and
the limits are looked at, then enforced: five failed logins for one email from one
address are answered, the sixth is a 429.
"""
import json

from tests.unit.test_production_startup import _run

_SCRIPT = """
import json, sys
from unittest.mock import MagicMock, patch

with patch("app.services.service_factory.ServiceFactory.create_all", return_value=MagicMock()):
    from app import create_app
    app = create_app(sys.argv[1])

from app.core.database import db
from app.core.extensions import limiter
with app.app_context():
    db.create_all()               # test setup only: production builds its schema with Alembic

keys = ("RATE_LIMIT_DEFAULT", "RATE_LIMIT_LOGIN_IP", "RATE_LIMIT_LOGIN_IP_EMAIL",
        "RATE_LIMIT_LOGIN_EMAIL", "RATE_LIMIT_REGISTER", "RATE_LIMIT_REFRESH", "RATE_LIMIT_LLM")
client = app.test_client()
statuses = [
    client.post("/api/v1/auth/login",
                json={"email": "nobody@example.com", "password": "wrong-password", "role": "candidate"}).status_code
    for _ in range(7)
]
print(json.dumps({
    "enabled": bool(limiter.enabled),
    "config_enabled": app.config.get("RATELIMIT_ENABLED", True),
    "limits": {k: app.config[k] for k in keys},
    "login_statuses": statuses,
}))
"""


def _boot_production(tmp_path):
    out = _run("production", tmp_path / "prod.db", script=_SCRIPT)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_production_has_the_limiter_on_with_the_real_limits(tmp_path):
    result = _boot_production(tmp_path)

    assert result["enabled"] is True
    assert result["config_enabled"] is True
    assert result["limits"] == {
        "RATE_LIMIT_DEFAULT":        "200 per minute",
        "RATE_LIMIT_LOGIN_IP":       "10 per minute",
        "RATE_LIMIT_LOGIN_IP_EMAIL": "5 per minute",
        "RATE_LIMIT_LOGIN_EMAIL":    "30 per hour",
        "RATE_LIMIT_REGISTER":       "10 per hour",
        "RATE_LIMIT_REFRESH":        "30 per minute",
        "RATE_LIMIT_LLM":            "10 per minute;100 per day",
    }


def test_production_stops_a_sixth_login_attempt_for_the_same_email_and_address(tmp_path):
    statuses = _boot_production(tmp_path)["login_statuses"]

    assert statuses == [401] * 5 + [429] * 2
