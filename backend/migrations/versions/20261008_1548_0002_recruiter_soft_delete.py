"""recruiter soft delete

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-08 15:48:22.833270+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'recruiters',
        sa.Column('is_deleted', sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        'recruiters',
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(op.f('ix_recruiters_is_deleted'), 'recruiters', ['is_deleted'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_recruiters_is_deleted'), table_name='recruiters')
    op.drop_column('recruiters', 'deleted_at')
    op.drop_column('recruiters', 'is_deleted')
