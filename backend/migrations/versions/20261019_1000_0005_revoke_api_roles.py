"""revoke the Supabase API roles' privileges on the public schema's tables and sequences

Supabase gives its anon and authenticated roles privileges on the tables and sequences in the
public schema, and by default on those created there later. The app connects directly as the
postgres role and never uses the generated REST API (the Data API), so those privileges only
widen the exposure. This migration changes permissions only: no table, column, index,
constraint or data changes.

For each of anon and authenticated:
  - REVOKE ALL on every existing table and sequence in public
  - ALTER DEFAULT PRIVILEGES ... REVOKE ALL ON TABLES and ON SEQUENCES in public, for the role
    running the migration, so what it creates later starts without them
  - the same default-privileges statements FOR ROLE postgres, when the migration runs as
    postgres or as a member of it (Supabase's tables belong to postgres)
service_role is left alone.

Every statement is guarded: on a database without the role (plain PostgreSQL, SQLite) it does
nothing. Functions are not touched: the app defines none in public (a test asserts it).

The downgrade does nothing, on purpose: re-granting would reopen the exposure. Anyone who
wants the privileges back grants them by hand.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-19 10:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

API_ROLES = ("anon", "authenticated")
OWNER_ROLE = "postgres"
KINDS = ("TABLES", "SEQUENCES")


def _revoke_from(role: str) -> str:
    existing = "".join(
        f"        EXECUTE 'REVOKE ALL ON ALL {kind} IN SCHEMA public FROM {role}';\n" for kind in KINDS
    )
    own_defaults = "".join(
        f"        EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON {kind} FROM {role}';\n"
        for kind in KINDS
    )
    owner_defaults = "".join(
        f"            EXECUTE 'ALTER DEFAULT PRIVILEGES FOR ROLE {OWNER_ROLE} IN SCHEMA public REVOKE ALL ON {kind} FROM {role}';\n"
        for kind in KINDS
    )
    return f"""
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
{existing}{own_defaults}        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{OWNER_ROLE}')
           AND pg_has_role(current_user, '{OWNER_ROLE}', 'USAGE') THEN
{owner_defaults}        END IF;
    END IF;
END
$$
"""


def upgrade() -> None:
    if op.get_context().dialect.name != "postgresql":
        return
    for role in API_ROLES:
        op.execute(_revoke_from(role))


def downgrade() -> None:
    """Intentionally empty: re-granting anon and authenticated would reopen the exposure."""
