"""notification delivery, prescriber date, taper start, doctor and pharmacy tables

Revision ID: 9c1a2b3d4e5f
Revises: 4831344ddf42
Create Date: 2026-11-14 18:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = "9c1a2b3d4e5f"
down_revision: Union[str, Sequence[str], None] = "4831344ddf42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("email", sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.create_unique_constraint("uq_users_email", ["email"])

    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.add_column(sa.Column("channel", sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(sa.Column("delivered_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True))
        batch_op.add_column(sa.Column("delivery_error", sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(
            sa.Column("delivery_attempts", sa.Integer(), nullable=False, server_default="0")
        )

    with op.batch_alter_table("prescriptions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("prescribed_on", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True))

    with op.batch_alter_table("taper_schedules", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "started_on",
                sqlmodel.sql.sqltypes.UTCDateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
        )

    op.create_table(
        "refill_orders",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("household_member_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("requested_by_user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("provider", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("provider_order_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("items_json", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("detail", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.Column("updated_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["household_member_id"], ["household_members.id"]),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("refill_orders", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_refill_orders_household_member_id"), ["household_member_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_refill_orders_status"), ["status"], unique=False)

    op.create_table(
        "doctor_grants",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("doctor_user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("household_member_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("granted_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.Column("expires_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True),
        sa.Column("last_viewed_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["doctor_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["household_member_id"], ["household_members.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("doctor_grants", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_doctor_grants_doctor_user_id"), ["doctor_user_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_doctor_grants_household_member_id"), ["household_member_id"], unique=False)

    op.create_table(
        "symptom_reports",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("household_member_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("reported_by_user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("symptom_text", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("severity", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("care_action", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["household_member_id"], ["household_members.id"]),
        sa.ForeignKeyConstraint(["reported_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("symptom_reports", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_symptom_reports_household_member_id"), ["household_member_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("symptom_reports", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_symptom_reports_household_member_id"))
    op.drop_table("symptom_reports")

    with op.batch_alter_table("doctor_grants", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_doctor_grants_household_member_id"))
        batch_op.drop_index(batch_op.f("ix_doctor_grants_doctor_user_id"))
    op.drop_table("doctor_grants")

    with op.batch_alter_table("refill_orders", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_refill_orders_status"))
        batch_op.drop_index(batch_op.f("ix_refill_orders_household_member_id"))
    op.drop_table("refill_orders")

    with op.batch_alter_table("taper_schedules", schema=None) as batch_op:
        batch_op.drop_column("started_on")

    with op.batch_alter_table("prescriptions", schema=None) as batch_op:
        batch_op.drop_column("prescribed_on")

    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.drop_column("delivery_attempts")
        batch_op.drop_column("delivery_error")
        batch_op.drop_column("delivered_at")
        batch_op.drop_column("channel")

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_constraint("uq_users_email", type_="unique")
        batch_op.drop_column("email")
