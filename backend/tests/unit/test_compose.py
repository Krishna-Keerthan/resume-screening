"""
docker-compose.yml runs the backend against its own Postgres container, which has no SSL.
The production default for DB_SSLMODE is "require", so compose must set it explicitly,
or a backend/.env with APP_ENV=production could not connect.
"""
import os

import yaml

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


def test_compose_sets_an_ssl_mode_its_local_postgres_accepts():
    with open(os.path.join(_REPO, "docker-compose.yml"), encoding="utf-8") as f:
        services = yaml.safe_load(f)["services"]

    (flask,) = [s for s in services.values() if s.get("container_name") == "ats_flask"]

    assert str(flask["environment"]["DB_SSLMODE"]) in ("disable", "prefer")
