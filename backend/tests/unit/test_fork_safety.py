"""
Fork safety. gunicorn loads the app in the master (preload_app) and forks the workers from
it, and SQLAlchemy's pooling documentation says a forked process must not inherit pooled
connections: https://docs.sqlalchemy.org/en/20/core/pooling.html (section "Using Connection
Pools with Multiprocessing or os.fork()"). Its recommended fix is Engine.dispose(close=False)
in the child, which gives it a new pool without closing the parent's connections.

Each case runs in a fresh interpreter, as test_production_startup.py does.
"""
import json

import pytest

from tests.unit.test_production_startup import _run

_BOOT = """
import json, sys
from unittest.mock import MagicMock, patch
from sqlalchemy import event
from sqlalchemy.engine import Engine

connects = []
event.listen(Engine, "connect", lambda dbapi, record: connects.append(1))

from app import create_app
from app.core.database import db
with patch("app.services.service_factory.ServiceFactory.create_all", return_value=MagicMock()):
    app = create_app(sys.argv[1])
with app.app_context():
    pool = db.engine.pool
    print(json.dumps({"connects": len(connects), "idle": pool.checkedin(), "in_use": pool.checkedout()}))
"""

_FORK = """
import json, runpy, sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import create_app
from app.core.database import db
with patch("app.services.service_factory.ServiceFactory.create_all", return_value=MagicMock()):
    app = create_app(sys.argv[1])

with app.app_context():
    parent_pool = db.engine.pool
    raw = db.engine.raw_connection()
    parent_connection = raw.dbapi_connection
    raw.close()                                   # back into the parent's pool, still open
    idle_before = parent_pool.checkedin()

    server = SimpleNamespace(app=SimpleNamespace(wsgi=lambda: app))
    runpy.run_path("gunicorn.conf.py")["post_fork"](server, SimpleNamespace(pid=1))

    try:
        parent_connection.execute("SELECT 1")
        parent_open = True
    except Exception:
        parent_open = False
    print(json.dumps({
        "idle_before": idle_before,
        "new_pool": db.engine.pool is not parent_pool,
        "new_pool_idle": db.engine.pool.checkedin(),
        "parent_connection_still_open": parent_open,
    }))
"""


def _last_json(out):
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("env_name, creates_tables", [("development", True), ("production", False)])
def test_create_app_leaves_no_connection_in_the_pool(tmp_path, env_name, creates_tables):
    result = _last_json(_run(env_name, tmp_path / "app.db", script=_BOOT))

    assert result["idle"] == 0 and result["in_use"] == 0
    assert (result["connects"] > 0) is creates_tables      # create_all connects, then lets go


def test_post_fork_gives_the_worker_a_new_pool_without_closing_the_parents_connections(tmp_path):
    result = _last_json(_run("development", tmp_path / "app.db", script=_FORK))

    assert result["idle_before"] == 1
    assert result["new_pool"] is True
    assert result["new_pool_idle"] == 0
    assert result["parent_connection_still_open"] is True
