"""storage_key comment no longer names Cloudinary

Changes only the comment on resumes.storage_key, which described the key as a Cloudinary
public_id. Cloudinary has been replaced by Supabase Storage. No data, column type or
constraint changes, and the table is not rewritten (a comment is catalogue metadata).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-17 09:00:00.000000+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_COMMENT = 'Cloudinary public_id (prod) or local file path (dev) — used for deletion'
NEW_COMMENT = 'Object key in the file store (Supabase Storage in prod) or local file path (dev) — used for deletion'


def _set_comment(comment: str, existing: str) -> None:
    op.alter_column(
        'resumes', 'storage_key',
        existing_type=sa.String(length=500),
        existing_nullable=True,
        comment=comment,
        existing_comment=existing,
    )


def upgrade() -> None:
    _set_comment(NEW_COMMENT, OLD_COMMENT)


def downgrade() -> None:
    _set_comment(OLD_COMMENT, NEW_COMMENT)
