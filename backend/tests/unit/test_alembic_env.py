"""
migrations/env.py hands the database driver the same connect_args as the app (DB_SSLMODE),
so a migration connects with the SSL mode the app does.

alembic runs in a fresh interpreter with engine_from_config replaced by a recorder, so no
database is needed. test_supabase_database.py checks it against a real server.
"""
import json
import os
import subprocess
import sys

import pytest

from tests.subprocess_env import subprocess_env

_BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

_SCRIPT = """
import json, sqlalchemy

seen = {}

class Stop(Exception):
    pass

def recorder(*args, **kwargs):
    seen["connect_args"] = kwargs.get("connect_args")
    raise Stop

sqlalchemy.engine_from_config = recorder
from alembic import command
from alembic.config import Config
try:
    command.upgrade(Config("alembic.ini"), "head")
except Stop:
    pass
print(json.dumps(seen))
"""


def _connect_args_seen_by_alembic(url, **env):
    out = subprocess.run(
        [sys.executable, "-c", _SCRIPT], cwd=_BACKEND, capture_output=True, text=True, check=True,
        env=subprocess_env(APP_ENV="development", DATABASE_URL=url, **env),
    )
    return json.loads(out.stdout.strip().splitlines()[-1])["connect_args"]


@pytest.mark.parametrize("mode", ["require", "verify-full"])
def test_a_postgres_migration_connects_with_the_configured_ssl_mode(mode):
    seen = _connect_args_seen_by_alembic("postgresql://u:p@localhost:1/x", DB_SSLMODE=mode)

    assert seen == {"sslmode": mode}


def test_a_migration_sends_no_ssl_mode_when_none_is_set():
    assert _connect_args_seen_by_alembic("postgresql://u:p@localhost:1/x") == {}


def test_a_sqlite_migration_is_never_given_an_ssl_mode():
    assert _connect_args_seen_by_alembic("sqlite:///x.db", DB_SSLMODE="require") == {}
