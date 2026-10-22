"""
The database on Supabase, through the session pooler. The checks that need a database skip
unless BOTH TEST_SUPABASE_DATABASE_URL (the session-pooler URL, port 5432, of a THROWAWAY Supabase
project) and RUN_SUPABASE_TESTS=1 are set. They run `alembic upgrade head`, then
`alembic downgrade base`, which drops every table the app owns. They refuse to run if the database
already has tables other than `alembic_version`, and, when the host is Supabase, unless
CONFIRM_SUPABASE_REF equals the project ref in the URL's user name (`postgres.<ref>`). The ref is
printed; the URL never is.

Run it with `scripts/run_supabase_check.sh database`, which reads those variables from backend/.env
and sets RUN_SUPABASE_TESTS itself. A plain `pytest` skips these tests.

They use the production settings (APP_ENV=production). DATABASE_URL and DB_SSLMODE come from the
URL above and the environment (DB_SSLMODE defaults to `require`; use `disable` for a local
Postgres without SSL). Every other setting ProductionConfig insists on gets a made-up placeholder:
SECRET_KEY, and RATE_LIMIT_STORAGE_URL, which points at a host under `.invalid` that cannot
resolve. No Redis is needed and none is contacted: a test checks that nothing looks that host up.

They check, with those settings:
  - the production defaults (SSL mode, pool size) reach the app's engine, and port 6543 is refused
    by both the app's config and Alembic's own connection;
  - the app's engine connects, over SSL unless DB_SSLMODE=disable, and does one repository round trip;
  - Alembic runs through the pooler, via migrations/env.py's connect_args path;
  - after upgrade head, anon and authenticated hold no grants in public (migration 0005);
  - DB_SSLMODE reaches Alembic's own connection: with verify-full and a root certificate that
    does not exist, the migration must fail on the certificate.
The URL and password are never printed by this test.
"""
import importlib.util
import os
import socket
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url

URL = os.getenv("TEST_SUPABASE_DATABASE_URL")
CONFIRMED_REF = os.getenv("CONFIRM_SUPABASE_REF")
RUN_ENV_VAR = "RUN_SUPABASE_TESTS"


def _enabled(url, run_flag):
    """These tests change a real database, so a URL alone (it could come from anywhere) is not enough."""
    return bool(url) and run_flag == "1"


requires_url = pytest.mark.skipif(
    not _enabled(URL, os.getenv(RUN_ENV_VAR)),
    reason=f"set TEST_SUPABASE_DATABASE_URL and {RUN_ENV_VAR}=1 (scripts/run_supabase_check.sh database does)",
)

_BACKEND = Path(__file__).resolve().parents[2]

_FAKE_REDIS_HOST = "redis-not-contacted.invalid"
# The settings ProductionConfig refuses to start without, apart from DATABASE_URL.
_PLACEHOLDERS = {
    "APP_ENV": "production",
    "SECRET_KEY": "x" * 64,
    "RATE_LIMIT_STORAGE_URL": f"redis://{_FAKE_REDIS_HOST}:6379/0",
}
# Production defaults under test: an environment override would hide them.
_DEFAULTED = ("DB_POOL_SIZE", "DB_MAX_OVERFLOW")


def _subprocess_env(**overrides):
    environment = {**os.environ, **_PLACEHOLDERS, "DATABASE_URL": URL, **overrides}
    for name in _DEFAULTED:
        environment.pop(name, None)
    return environment


def _alembic(*args, **env):
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=_BACKEND, env=_subprocess_env(**env),
        capture_output=True, text=True,
    )


def _table_names(engine, schema="public"):
    return set(sa.inspect(engine).get_table_names(schema=schema))


def _project_ref(url):
    """The Supabase project ref (the part of the pooler user name after 'postgres.'), or None
    when the host is not Supabase. Raises ValueError when it is Supabase but has no ref."""
    parsed = make_url(url)
    if "supabase" not in (parsed.host or ""):
        return None
    username = parsed.username or ""
    if "." not in username:
        raise ValueError("the user name has no project ref: use the session-pooler URL (postgres.<ref>)")
    return username.split(".", 1)[1]


def _confirm_target(url, confirmed_ref):
    """Fail, before anything is changed, unless a Supabase target was confirmed by its ref.
    Returns the ref ('' for a non-Supabase host). Messages carry the ref, never the URL."""
    try:
        ref = _project_ref(url)
    except ValueError as error:
        pytest.fail(str(error))
    if ref is None:
        return ""
    if confirmed_ref != ref:
        pytest.fail(f"this URL targets Supabase project '{ref}'. To run against it, set "
                    f"CONFIRM_SUPABASE_REF={ref}. Nothing was changed.")
    return ref


def _refuse_unless_empty(engine, schema="public"):
    """Fail before anything is run if the database holds tables other than alembic_version."""
    foreign = _table_names(engine, schema) - {"alembic_version"}
    if foreign:
        pytest.fail(f"the database already has {len(foreign)} table(s) besides alembic_version: "
                    "use an empty, throwaway Supabase project")


@pytest.fixture(scope="module")
def production_env():
    """Placeholders and the database URL in os.environ for the module; yields the host names
    Python looked up meanwhile."""
    lookups = []
    real_getaddrinfo = socket.getaddrinfo

    def recording_getaddrinfo(host, *args, **kwargs):
        lookups.append(host)
        return real_getaddrinfo(host, *args, **kwargs)

    with pytest.MonkeyPatch.context() as mp:
        for name, value in _PLACEHOLDERS.items():
            mp.setenv(name, value)
        mp.setenv("DATABASE_URL", URL or "")
        for name in _DEFAULTED:
            mp.delenv(name, raising=False)
        mp.setattr(socket, "getaddrinfo", recording_getaddrinfo)
        yield lookups


@pytest.fixture(scope="module")
def settings(production_env):
    """A private copy of config/settings.py, executed under the environment above. The class
    attributes there are read from the environment when the module runs, so the copy that other
    tests imported earlier (with their environment) cannot be used. (conftest has already replaced
    load_dotenv, so no .env fills a gap.)"""
    spec = importlib.util.spec_from_file_location("settings_under_test", _BACKEND / "config" / "settings.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def app(settings, request):
    """A minimal Flask app on the app's own production config and database setup. No limiter, no
    services: nothing here talks to Redis."""
    from flask import Flask

    from app.core.database import db, init_db

    ref = _confirm_target(URL, CONFIRMED_REF)   # before the app can reach the database
    if ref:
        reporter = request.config.pluginmanager.get_plugin("terminalreporter")
        if reporter:
            reporter.write_line(f"\nSupabase project ref: {ref}")
    app = Flask(__name__)
    app.config.from_object(settings.ProductionConfig())
    init_db(app)
    with app.app_context():
        _refuse_unless_empty(db.engine)   # before the first statement that changes anything
        yield app
        db.session.remove()
        _alembic("downgrade", "base")
        db.engine.dispose()


def test_the_guard_refuses_a_database_that_has_tables():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE candidates (id INTEGER)"))
        connection.execute(sa.text("CREATE TABLE alembic_version (version_num VARCHAR)"))

    with pytest.raises(pytest.fail.Exception, match="1 table"):
        _refuse_unless_empty(engine, schema=None)


@pytest.mark.parametrize("tables", [[], ["alembic_version"]])
def test_the_guard_accepts_an_empty_database_or_one_that_only_has_alembic_version(tables):
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        for table in tables:
            connection.execute(sa.text(f"CREATE TABLE {table} (version_num VARCHAR)"))

    _refuse_unless_empty(engine, schema=None)


@requires_url
def test_the_production_defaults_reach_the_apps_engine(app):
    from app.core.database import db

    assert app.config["DB_SSLMODE"] == os.getenv("DB_SSLMODE", "require")
    assert (app.config["DB_POOL_SIZE"], app.config["DB_MAX_OVERFLOW"]) == (3, 2)
    assert db.engine.pool.size() == 3
    assert db.engine.pool._max_overflow == 2


@requires_url
def test_port_6543_is_refused_by_the_app_config_and_by_alembic(settings, monkeypatch):
    transaction_mode_url = make_url(URL).set(port=6543).render_as_string(hide_password=False)
    monkeypatch.setenv("DATABASE_URL", transaction_mode_url)

    with pytest.raises(EnvironmentError, match="6543"):
        settings.ProductionConfig().SQLALCHEMY_DATABASE_URI

    result = _alembic("current", DATABASE_URL=transaction_mode_url)
    assert result.returncode != 0
    assert "6543" in result.stderr
    assert transaction_mode_url not in result.stderr + result.stdout


@requires_url
def test_the_app_connects_with_the_configured_ssl_mode(app):
    from app.core.database import db

    # pg_stat_ssl would report the pooler-to-Postgres hop, not the app's own connection.
    driver_connection = db.session.connection().connection.driver_connection

    assert driver_connection.info.ssl_in_use is (app.config["DB_SSLMODE"] != "disable")


@requires_url
def test_db_sslmode_reaches_alembics_own_connection(app):
    result = _alembic("current", DB_SSLMODE="verify-full", PGSSLROOTCERT="/nonexistent/root.crt")

    # A server without SSL (a local Postgres, DB_SSLMODE=disable) refuses before any certificate
    # is read; Supabase gets as far as the missing root certificate.
    expected = "does not support ssl" if os.getenv("DB_SSLMODE") == "disable" else "root certificate"
    assert result.returncode != 0
    assert expected in result.stderr.lower()


@requires_url
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


@requires_url
def test_downgrade_to_base_removes_the_tables(app):
    from app.core.database import db

    db.session.remove()  # an open transaction on candidates would block the DROP INDEX
    downgraded = _alembic("downgrade", "base")

    assert downgraded.returncode == 0, downgraded.stderr[-600:]
    assert _table_names(db.engine) <= {"alembic_version"}


@requires_url
def test_the_placeholder_redis_host_was_never_looked_up(app, production_env):
    # Python-level lookups only: psycopg resolves the database host inside libpq. The Alembic
    # subprocesses build no limiter either, and the host would not resolve anyway (.invalid).
    assert _FAKE_REDIS_HOST not in production_env


# ─── Gate and confirmation: these run without any database ───────────────────

def test_the_tests_need_both_the_url_and_the_run_flag():
    assert _enabled("postgresql://u:p@h/db", "1") is True
    assert _enabled("postgresql://u:p@h/db", None) is False
    assert _enabled("postgresql://u:p@h/db", "0") is False
    assert _enabled("postgresql://u:p@h/db", "true") is False
    assert _enabled(None, "1") is False
    assert _enabled("", "1") is False


def _pytest_on_this_file(**env):
    environment = {k: v for k, v in os.environ.items()
                   if k not in ("TEST_SUPABASE_DATABASE_URL", RUN_ENV_VAR, "CONFIRM_SUPABASE_REF")}
    environment.update(env)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", "-rs", "-k", "not gate_subprocess",
         "tests/integration/test_supabase_database.py"],
        cwd=_BACKEND, env=environment, capture_output=True, text=True,
    )


_UNREACHABLE_URL = "postgresql://u:Zq9notprinted@host.invalid:5432/db"


def test_gate_subprocess_a_plain_pytest_skips_the_database_tests_even_with_the_url_set():
    done = _pytest_on_this_file(TEST_SUPABASE_DATABASE_URL=_UNREACHABLE_URL)

    assert done.returncode == 0, done.stdout[-800:]
    assert "7 skipped" in done.stdout
    assert RUN_ENV_VAR in done.stdout   # the skip reason says what to set
    assert "Zq9notprinted" not in done.stdout + done.stderr


def test_gate_subprocess_with_the_flag_the_database_tests_are_attempted():
    done = _pytest_on_this_file(TEST_SUPABASE_DATABASE_URL=_UNREACHABLE_URL, **{RUN_ENV_VAR: "1"})

    assert "skipped" not in done.stdout   # they ran, and failed on the unreachable host
    assert done.returncode != 0
    assert "Zq9notprinted" not in done.stdout + done.stderr


def test_the_project_ref_comes_from_the_pooler_user_name():
    url = "postgresql://postgres.abcdefghij:secret@aws-0-eu-west-1.pooler.supabase.com:5432/postgres"

    assert _project_ref(url) == "abcdefghij"


def test_a_non_supabase_host_has_no_ref_and_needs_no_confirmation():
    assert _project_ref("postgresql://postgres:test@localhost:55432/db") is None
    assert _confirm_target("postgresql://postgres:test@localhost:55432/db", None) == ""


def test_a_supabase_url_without_a_ref_in_the_user_name_is_refused():
    with pytest.raises(pytest.fail.Exception, match="project ref"):
        _confirm_target("postgresql://postgres:secret@db.abcdefghij.supabase.co:5432/postgres", "abcdefghij")


SUPABASE_URL = "postgresql://postgres.abcdefghij:secret@aws-0-eu-west-1.pooler.supabase.com:5432/postgres"


@pytest.mark.parametrize("confirmed", [None, "", "otherproject", "ABCDEFGHIJ"])
def test_a_supabase_target_needs_the_matching_ref_and_the_message_hides_the_url(confirmed):
    with pytest.raises(pytest.fail.Exception) as raised:
        _confirm_target(SUPABASE_URL, confirmed)

    message = str(raised.value)
    assert "CONFIRM_SUPABASE_REF=abcdefghij" in message
    assert "secret" not in message and "pooler.supabase.com" not in message


def test_the_matching_ref_is_accepted_and_returned():
    assert _confirm_target(SUPABASE_URL, "abcdefghij") == "abcdefghij"
