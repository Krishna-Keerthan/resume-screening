"""case-insensitive unique emails

Normalises every stored email to lower(trim(email)) and replaces
case-sensitive uniqueness with unique indexes on lower(email), on both
candidates and recruiters.

The upgrade refuses to run if two rows in one table would collide once
normalised; it lists them and changes nothing. Resolve them by hand first.
The normalising UPDATE is not reversible, so the downgrade only drops the
indexes.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-13 12:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = {
    'candidates': 'uq_candidates_email_lower',
    'recruiters': 'uq_recruiters_email_lower',
}


def _duplicate_emails(table: str) -> list[str]:
    rows = op.get_bind().execute(sa.text(
        f"SELECT lower(trim(email)) AS normalised, id, email FROM {table} "
        f"WHERE lower(trim(email)) IN ("
        f"  SELECT lower(trim(email)) FROM {table} "
        f"  GROUP BY lower(trim(email)) HAVING count(*) > 1"
        f") ORDER BY normalised, id"
    )).all()
    return [f"{table}: {r.normalised} -> id={r.id} email={r.email!r}" for r in rows]


def upgrade() -> None:
    duplicates = [line for table in _TABLES for line in _duplicate_emails(table)]
    if duplicates:
        raise RuntimeError(
            "Cannot make emails case-insensitively unique: these rows collide "
            "once lowercased and trimmed. Merge or delete them, then re-run.\n"
            + "\n".join(duplicates)
        )

    for table, index in _TABLES.items():
        op.execute(f"UPDATE {table} SET email = lower(trim(email)) WHERE email <> lower(trim(email))")
        op.create_index(index, table, [sa.text('lower(email)')], unique=True)


def downgrade() -> None:
    for table, index in _TABLES.items():
        op.drop_index(index, table_name=table)
