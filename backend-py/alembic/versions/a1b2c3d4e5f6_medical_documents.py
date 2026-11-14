"""unified medical document intake

Revision ID: a1b2c3d4e5f6
Revises: 9c1a2b3d4e5f
Create Date: 2026-11-14 19:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "9c1a2b3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "medical_documents",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("household_member_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("document_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("original_filename", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("mime_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("file_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("file_storage_key", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("ocr_status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("ocr_error", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("raw_text", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("extracted_json", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("captured_on", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("uploaded_by_user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.Column("updated_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["household_member_id"], ["household_members.id"]),
        sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("medical_documents", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_medical_documents_household_member_id"), ["household_member_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_medical_documents_document_type"), ["document_type"], unique=False)
        batch_op.create_index(batch_op.f("ix_medical_documents_ocr_status"), ["ocr_status"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("medical_documents", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_medical_documents_ocr_status"))
        batch_op.drop_index(batch_op.f("ix_medical_documents_document_type"))
        batch_op.drop_index(batch_op.f("ix_medical_documents_household_member_id"))
    op.drop_table("medical_documents")
