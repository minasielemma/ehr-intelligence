"""Create fhir_bundles table for persisted HL7 FHIR R4 Bundles.

Revision ID: 0004_create_fhir_bundles
Revises: 0003_add_provenance_patient_id
Create Date: 2026-11-21 17:18:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0004_create_fhir_bundles"
down_revision: Union[str, None] = "0003_add_provenance_patient_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()
    if "fhir_bundles" not in existing_tables:
        op.create_table(
            "fhir_bundles",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("bundle_id", sa.String(length=64), nullable=False),
            sa.Column("patient_id", sa.String(length=36), nullable=False),
            sa.Column("patient_mrn", sa.String(length=128), nullable=False),
            sa.Column("bundle_type", sa.String(length=32), nullable=False, server_default="collection"),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="VALID"),
            sa.Column("resource_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("content_hash", sa.String(length=64), nullable=False),
            sa.Column("bundle_json", sa.JSON(), nullable=False),
            sa.Column("validation_report_json", sa.JSON(), nullable=True),
            sa.Column("file_path", sa.String(length=255), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_fhir_bundles_bundle_id", "fhir_bundles", ["bundle_id"], unique=True)
        op.create_index("ix_fhir_bundles_patient_id", "fhir_bundles", ["patient_id"])
        op.create_index("ix_fhir_bundles_patient_mrn", "fhir_bundles", ["patient_mrn"])
        op.create_index("ix_fhir_bundles_bundle_type", "fhir_bundles", ["bundle_type"])
        op.create_index("ix_fhir_bundles_content_hash", "fhir_bundles", ["content_hash"])
        op.create_index("ix_fhir_bundles_status", "fhir_bundles", ["status"])
        op.create_index("ix_fhir_bundle_patient_version", "fhir_bundles", ["patient_id", "version"], unique=True)


def downgrade() -> None:
    op.drop_table("fhir_bundles")
