"""
Migration 0005 revokes Supabase's anon and authenticated roles' privileges on the public
schema's tables and sequences, now and by default. It needs PostgreSQL (set TEST_DATABASE_URL,
as for the rest of the suite) and the postgres role, which can create databases and roles.
Each test migrates its own scratch database; the roles are cluster-wide, so a test creates
them and drops them again, and refuses to run if the cluster already has them.
"""
import os
import subprocess
import sys
import uuid

import pytest
import sqlalchemy as sa

ADMIN_URL = os.getenv("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not ADMIN_URL.startswith("postgresql"), reason="needs PostgreSQL (set TEST_DATABASE_URL)",
)

_BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
API_ROLES = ("anon", "authenticated")
TABLE_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
SEQUENCE_PRIVILEGES = ("USAGE", "SELECT", "UPDATE")


@pytest.fixture()
def admin():
    engine = sa.create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with engine.connect() as connection:
        if connection.execute(sa.text("SELECT current_user")).scalar() != "postgres":
            pytest.skip("run as the postgres role")
        yield connection
    engine.dispose()


def _scratch(admin, owner=None):
    """Create an empty database (owned by `owner`), yield (url, engine), drop it afterwards."""
    name = f"ats_m0005_{uuid.uuid4().hex[:8]}"
    admin.execute(sa.text(f'CREATE DATABASE "{name}"' + (f" OWNER {owner}" if owner else "")))
    url = sa.engine.make_url(ADMIN_URL).set(database=name)
    engine = sa.create_engine(url, isolation_level="AUTOCOMMIT")
    try:
        yield url, engine
    finally:
        engine.dispose()
        admin.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@pytest.fixture()
def scratch(admin):
    yield from _scratch(admin)


@pytest.fixture()
def api_roles(admin):
    """anon, authenticated and service_role, created for the test and dropped after it.

    Request this fixture before `scratch` so the scratch database is dropped first.
    """
    wanted = (*API_ROLES, "service_role")
    present = {r for (r,) in admin.execute(sa.text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:r)"), {"r": list(wanted)})}
    if present:
        pytest.skip(f"the cluster already has {sorted(present)}; refusing to touch real roles")
    for role in wanted:
        admin.execute(sa.text(f"CREATE ROLE {role} NOLOGIN"))
    yield wanted
    for role in wanted:
        admin.execute(sa.text(f"DROP ROLE IF EXISTS {role}"))


@pytest.fixture()
def migrator(admin):
    """A login role that is NOT postgres. The test creates a database it owns. Dropped after it."""
    role = f"m0005_owner_{uuid.uuid4().hex[:6]}"
    admin.execute(sa.text(f"CREATE ROLE {role} LOGIN PASSWORD 'pw'"))
    yield role
    admin.execute(sa.text(f"DROP ROLE IF EXISTS {role}"))


def _alembic(url, *args):
    env = {k: v for k, v in os.environ.items() if k not in ("DB_SSLMODE",)}
    env.update(APP_ENV="development", DATABASE_URL=url.render_as_string(hide_password=False))
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=_BACKEND, env=env, capture_output=True, text=True,
    )


def _privileges(engine, role):
    """Every (relation, privilege) on public tables and sequences that the role holds."""
    held = set()
    with engine.connect() as connection:
        for relkinds, check, privileges in (
            ("'r','p'", "has_table_privilege", TABLE_PRIVILEGES),
            ("'S'", "has_sequence_privilege", SEQUENCE_PRIVILEGES),
        ):
            names = [n for (n,) in connection.execute(sa.text(
                "SELECT c.relname FROM pg_class c JOIN pg_namespace s ON s.oid = c.relnamespace "
                f"WHERE s.nspname = 'public' AND c.relkind IN ({relkinds})"))]
            for name in names:
                for privilege in privileges:
                    granted = connection.execute(
                        sa.text(f"SELECT {check}(:r, :n, :p)"), {"r": role, "n": f'public."{name}"', "p": privilege},
                    ).scalar()
                    if granted:
                        held.add((name, privilege))
    return held


def _grant_like_supabase(engine, owner_role, roles):
    """Grants on what exists and, by default, on what `owner_role` creates next."""
    with engine.connect() as connection:
        for role in roles:
            connection.execute(sa.text(f"GRANT ALL ON ALL TABLES IN SCHEMA public TO {role}"))
            connection.execute(sa.text(f"GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO {role}"))
            for kind in ("TABLES", "SEQUENCES"):
                connection.execute(sa.text(
                    f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner_role} IN SCHEMA public GRANT ALL ON {kind} TO {role}"))


def test_it_runs_on_a_plain_database_without_the_roles(admin, scratch):
    url, engine = scratch
    if admin.execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = ANY(:r)"), {"r": list(API_ROLES)}).first():
        pytest.skip("the cluster has anon or authenticated; this test needs a plain database")

    upgraded = _alembic(url, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr[-600:]
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar() == "0005"

    downgraded = _alembic(url, "downgrade", "0004")
    assert downgraded.returncode == 0, downgraded.stderr[-600:]


def test_after_it_the_api_roles_have_nothing_on_our_tables_sequences_or_later_ones(admin, api_roles, scratch):
    url, engine = scratch
    assert _alembic(url, "upgrade", "0004").returncode == 0
    with engine.connect() as connection:
        connection.execute(sa.text("CREATE SEQUENCE sequence_before"))
    _grant_like_supabase(engine, "postgres", ("anon", "authenticated", "service_role"))
    assert _privileges(engine, "anon"), "the setup should have granted anon something"

    upgraded = _alembic(url, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr[-600:]

    for role in API_ROLES:
        assert _privileges(engine, role) == set(), role
    with engine.connect() as connection:
        connection.execute(sa.text("CREATE TABLE created_later (id integer PRIMARY KEY)"))
        connection.execute(sa.text("CREATE SEQUENCE sequence_later"))
    for role in API_ROLES:
        assert _privileges(engine, role) == set(), f"{role} on something created afterwards"
    service = _privileges(engine, "service_role")                                  # left alone
    assert {("candidates", "SELECT"), ("created_later", "SELECT"), ("sequence_before", "USAGE"), ("sequence_later", "USAGE")} <= service


def test_a_migrator_that_is_not_postgres_leaves_later_tables_without_the_api_roles(admin, api_roles, migrator):
    # Default privileges belong to the role that creates the objects. Here that is not postgres.
    for url, engine in _scratch(admin, owner=migrator):
        url = url.set(username=migrator, password="pw")
        assert _alembic(url, "upgrade", "0004").returncode == 0
        _grant_like_supabase(engine, migrator, API_ROLES)
        assert _privileges(engine, "anon"), "the setup should have granted anon something"

        upgraded = _alembic(url, "upgrade", "head")
        assert upgraded.returncode == 0, upgraded.stderr[-600:]

        owner_engine = sa.create_engine(url, isolation_level="AUTOCOMMIT")
        with owner_engine.connect() as connection:
            connection.execute(sa.text("CREATE TABLE created_later (id integer PRIMARY KEY)"))
            connection.execute(sa.text("CREATE SEQUENCE sequence_later"))
        owner_engine.dispose()
        for role in API_ROLES:
            assert _privileges(engine, role) == set(), role


def test_the_downgrade_does_not_give_the_privileges_back(admin, api_roles, scratch):
    url, engine = scratch
    assert _alembic(url, "upgrade", "head").returncode == 0

    assert _alembic(url, "downgrade", "0004").returncode == 0

    for role in API_ROLES:
        assert _privileges(engine, role) == set()


def test_the_app_schema_defines_no_functions_in_public(admin, scratch):
    # Why 0005 does not touch functions: there is nothing to revoke on.
    url, engine = scratch
    assert _alembic(url, "upgrade", "head").returncode == 0

    with engine.connect() as connection:
        count = connection.execute(sa.text(
            "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'public'")).scalar()

    assert count == 0
