"""revoked marker on caregiver access

Revision ID: d8e9f0a1b2c3
Revises: c3d4e5f6a7b8
Create Date: 2026-11-17 15:10:00.000000

A revoke must be permanent for that grant. Without a marker, a revoke that only cleared
the consent row could be undone by the caregiver recording consent again.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'd8e9f0a1b2c3'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('caregiver_access', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('revoked_at', sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True)
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('caregiver_access', schema=None) as batch_op:
        batch_op.drop_column('revoked_at')
