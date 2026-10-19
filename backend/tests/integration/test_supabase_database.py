"""
The database on Supabase, through the session pooler. Skipped unless TEST_SUPABASE_DATABASE_URL
is set, to the session-pooler URL (port 5432) of a THROWAWAY Supabase project: this test runs
`alembic upgrade head`, then `alembic downgrade base`, which drops every table the app owns.
It refuses to run if the database already has tables.

  TEST_SUPABASE_DATABASE_URL=postgresql://postgres.<ref>:<password>@<pooler-host>:5432/postgres \
      pytest -q tests/integration/test_supabase_database.py

It checks, with APP_ENV=production settings (DB_SSLMODE=require unless you set it):
  - the app's engine connects over SSL and does one repository round trip;
  - Alembic runs through the pooler, via migrations/env.py's connect_args path;
  - after upgrade head, anon and authenticated hold no grants in public (migration 0005);
  - DB_SSLMODE reaches Alembic's own connection: with verify-full and a root certificate that
    does not exist, the migration must fail on the certificate.
The URL and password are never printed by this test.
"""
import os
import subprocess
import sys
import uuid

import pytest
import sqlalchemy as sa

URL = os.getenv("TEST_SUPABASE_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set TEST_SUPABASE_DATABASE_URL (throwaway Supabase project)")

_BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def _alembic(*args, **env):
    environment = {
        **os.environ,
        "APP_ENV": "production",
        "DATABASE_URL": URL,
        "SECRET_KEY": "x" * 64,
        "RATE_LIMIT_STORAGE_URL": "redis://unused:6379/0",
        "DB_SSLMODE": os.getenv("DB_SSLMODE", "require"),
        **env,
    }
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=_BACKEND, env=environment,
        capture_output=True, text=True,
    )


def _table_names(engine):
    return set(sa.inspect(engine).get_table_names(schema="public"))


@pytest.fixture(scope="module")
def app():
    """A minimal Flask app on the app's own production config and database setup."""
    from flask import Flask

    from app.core.database import init_db
    from config.settings import ProductionConfig

    os.environ.update(APP_ENV="production", DATABASE_URL=URL, SECRET_KEY="x" * 64,
                      RATE_LIMIT_STORAGE_URL="redis://unused:6379/0")
    os.environ.setdefault("DB_SSLMODE", "require")
    app = Flask(__name__)
    app.config.from_object(ProductionConfig())
    init_db(app)
    with app.app_context():
        from app.core.database import db

        if _table_names(db.engine):
            pytest.fail("the database already has tables: use an empty, throwaway Supabase project")
        yield app
        db.session.remove()
        _alembic("downgrade", "base")
        db.engine.dispose()


def test_the_app_connects_over_ssl(app):
    from app.core.database import db

    ssl = db.session.execute(sa.text("SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()")).scalar()

    assert ssl is True


def test_db_sslmode_reaches_alembics_own_connection(app):
    result = _alembic("current", DB_SSLMODE="verify-full", PGSSLROOTCERT="/nonexistent/root.crt")

    assert result.returncode != 0
    assert "root certificate" in result.stderr.lower()


def test_migrations_run_through_the_session_pooler_and_a_repository_round_trips(app):
    from app.core.database import db
    from app.models.candidate import Candidate
    from app.repositories.candidate import CandidateRepository

    upgraded = _alembic("upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr[-600:]
    assert {"candidates", "alembic_version"} <= _table_names(db.engine)

    # migration 0005: Supabase's anon and authenticated roles hold nothing in public (counts only)
    table_grants = db.session.execute(sa.text(
        "SELECT count(*) FROM information_schema.role_table_grants "
        "WHERE table_schema = 'public' AND grantee IN ('anon', 'authenticated')")).scalar()
    sequence_grants = db.session.execute(sa.text(
        "SELECT count(*) FROM information_schema.role_usage_grants "
        "WHERE object_schema = 'public' AND object_type = 'SEQUENCE' AND grantee IN ('anon', 'authenticated')")).scalar()
    assert (table_grants, sequence_grants) == (0, 0), (
        f"anon/authenticated still hold {table_grants} table grants and {sequence_grants} sequence grants"
    )

    repo = CandidateRepository()
    email = f"pooler-{uuid.uuid4().hex[:8]}@example.com"
    repo.save(Candidate(full_name="Pooler Check", email=email, password_hash="x" * 60))
    repo.commit()

    found = repo.get_by_email(email)
    assert found is not None and found.full_name == "Pooler Check"
    repo.delete(found)
    repo.commit()
    assert repo.get_by_email(email) is None


def test_downgrade_to_base_removes_the_tables(app):
    from app.core.database import db

    downgraded = _alembic("downgrade", "base")

    assert downgraded.returncode == 0, downgraded.stderr[-600:]
    assert _table_names(db.engine) <= {"alembic_version"}
