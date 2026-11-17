"""conditions table for the longitudinal record

Revision ID: c3d4e5f6a7b8
Revises: a1b2c3d4e5f6
Create Date: 2026-11-17 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('conditions',
    sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('household_member_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('name_raw', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('status', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('onset_date', sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True),
    sa.Column('source_prescription_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('source_document_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('confirmed', sa.Boolean(), nullable=False),
    sa.Column('confirmed_at', sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True),
    sa.Column('confirmed_by_user_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('created_at', sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
    sa.Column('updated_at', sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['household_member_id'], ['household_members.id'], ),
    sa.ForeignKeyConstraint(['source_prescription_id'], ['prescriptions.id'], ),
    sa.ForeignKeyConstraint(['source_document_id'], ['medical_documents.id'], ),
    sa.ForeignKeyConstraint(['confirmed_by_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('conditions', schema=None) as batch_op:
        batch_op.create_index('ix_conditions_household_member_id', ['household_member_id'], unique=False)
        batch_op.create_index('ix_conditions_status', ['status'], unique=False)
        batch_op.create_index('ix_conditions_source_prescription_id', ['source_prescription_id'], unique=False)
        batch_op.create_index('ix_conditions_source_document_id', ['source_document_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('conditions', schema=None) as batch_op:
        batch_op.drop_index('ix_conditions_source_document_id')
        batch_op.drop_index('ix_conditions_source_prescription_id')
        batch_op.drop_index('ix_conditions_status')
        batch_op.drop_index('ix_conditions_household_member_id')

    op.drop_table('conditions')
