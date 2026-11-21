"""Create clinical_summaries table for AI-generated clinical summaries and caching.

Revision ID: 0005_create_clinical_summaries
Revises: 0004_create_fhir_bundles
Create Date: 2026-11-21 18:45:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0005_create_clinical_summaries"
down_revision: Union[str, None] = "0004_create_fhir_bundles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()
    if "clinical_summaries" not in existing_tables:
        op.create_table(
            "clinical_summaries",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("cache_key", sa.String(length=64), nullable=False),
            sa.Column("patient_id", sa.String(length=36), nullable=False),
            sa.Column("bundle_id", sa.String(length=64), nullable=True),
            sa.Column("bundle_hash", sa.String(length=64), nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("model_name", sa.String(length=64), nullable=False),
            sa.Column("prompt_version", sa.String(length=32), nullable=False, server_default="v1.0.0"),
            sa.Column("temperature", sa.Float(), nullable=False, server_default="0.1"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="COMPLETED"),
            sa.Column("summary_json", sa.JSON(), nullable=False),
            sa.Column("clinical_summary_text", sa.Text(), nullable=False),
            sa.Column("word_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("confidence_level", sa.String(length=16), nullable=False, server_default="high"),
            sa.Column("execution_time_ms", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("file_path", sa.String(length=255), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_clinical_summaries_cache_key", "clinical_summaries", ["cache_key"], unique=True)
        op.create_index("ix_clinical_summaries_patient_id", "clinical_summaries", ["patient_id"])
        op.create_index("ix_clinical_summaries_bundle_id", "clinical_summaries", ["bundle_id"])
        op.create_index("ix_clinical_summaries_bundle_hash", "clinical_summaries", ["bundle_hash"])
        op.create_index("ix_clinical_summaries_provider", "clinical_summaries", ["provider"])
        op.create_index("ix_clinical_summaries_status", "clinical_summaries", ["status"])
        op.create_index("ix_clinical_summary_patient_created", "clinical_summaries", ["patient_id", "created_at"])
        op.create_index("ix_clinical_summary_hash_model", "clinical_summaries", ["bundle_hash", "model_name"])


def downgrade() -> None:
    op.drop_table("clinical_summaries")
