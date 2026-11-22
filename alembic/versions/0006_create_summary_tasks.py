"""Create summary_tasks table for persistent asynchronous task tracking.

Revision ID: 0006_create_summary_tasks
Revises: 0005_create_clinical_summaries
Create Date: 2026-11-22 23:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0006_create_summary_tasks"
down_revision: Union[str, None] = "0005_create_clinical_summaries"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()
    if "summary_tasks" not in existing_tables:
        op.create_table(
            "summary_tasks",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("patient_id", sa.String(length=36), nullable=False),
            sa.Column("bundle_id", sa.String(length=64), nullable=True),
            sa.Column("force_refresh", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
            sa.Column("message", sa.String(length=255), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("duration_seconds", sa.Float(), nullable=True),
            sa.Column("summary_json", sa.JSON(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_summary_tasks_patient_id", "summary_tasks", ["patient_id"])
        op.create_index("ix_summary_tasks_bundle_id", "summary_tasks", ["bundle_id"])
        op.create_index("ix_summary_tasks_status", "summary_tasks", ["status"])
        op.create_index("ix_summary_tasks_patient_created", "summary_tasks", ["patient_id", "created_at"])


def downgrade() -> None:
    op.drop_table("summary_tasks")
