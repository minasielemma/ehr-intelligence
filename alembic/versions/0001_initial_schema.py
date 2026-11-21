"""Initial database schema for EHR ingestion and reconciliation.

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-11-21 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # 1. Ingestion Jobs
    if "ingestion_jobs" not in existing_tables:
        op.create_table(
            "ingestion_jobs",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("idempotency_key", sa.String(length=128), nullable=True),
            sa.Column("source_format", sa.String(length=32), nullable=False),
            sa.Column("source_system", sa.String(length=128), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("total_records", sa.Integer(), nullable=False),
            sa.Column("successful_records", sa.Integer(), nullable=False),
            sa.Column("rejected_records", sa.Integer(), nullable=False),
            sa.Column("duplicate_records", sa.Integer(), nullable=False),
            sa.Column("warning_records", sa.Integer(), nullable=False),
            sa.Column("conflict_records", sa.Integer(), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_ingestion_jobs_idempotency_key", "ingestion_jobs", ["idempotency_key"])
        op.create_index("ix_ingestion_jobs_status", "ingestion_jobs", ["status"])

    # 2. Patients
    if "patients" not in existing_tables:
        op.create_table(
            "patients",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("source_system", sa.String(length=128), nullable=False),
            sa.Column("source_patient_id", sa.String(length=128), nullable=True),
            sa.Column("mrn", sa.String(length=128), nullable=False),
            sa.Column("original_mrn", sa.String(length=128), nullable=True),
            sa.Column("first_name", sa.String(length=128), nullable=False),
            sa.Column("middle_name", sa.String(length=128), nullable=True),
            sa.Column("last_name", sa.String(length=128), nullable=False),
            sa.Column("date_of_birth", sa.String(length=32), nullable=True),
            sa.Column("original_date_of_birth", sa.String(length=64), nullable=True),
            sa.Column("administrative_gender", sa.String(length=32), nullable=False),
            sa.Column("original_gender", sa.String(length=64), nullable=True),
            sa.Column("contact_info", sa.JSON(), nullable=True),
            sa.Column("reconciliation_status", sa.String(length=32), nullable=False),
            sa.Column("confidence_score", sa.Float(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_patients_source_system", "patients", ["source_system"])
        op.create_index("ix_patients_source_patient_id", "patients", ["source_patient_id"])
        op.create_index("ix_patients_mrn", "patients", ["mrn"])
        op.create_index("ix_patients_date_of_birth", "patients", ["date_of_birth"])
        op.create_index("ix_patients_reconciliation_status", "patients", ["reconciliation_status"])
        op.create_index("ix_patient_source_mrn", "patients", ["source_system", "mrn"])
        op.create_index(
            "ix_patient_lower_source_mrn",
            "patients",
            [sa.text("lower(source_system)"), "mrn"],
        )
        op.create_index("ix_patient_name_dob", "patients", ["last_name", "first_name", "date_of_birth"])
        op.create_index(
            "ix_patient_lower_name_dob",
            "patients",
            [sa.text("lower(last_name)"), sa.text("lower(first_name)"), "date_of_birth"],
        )

    # 3. Patient Identifiers
    if "patient_identifiers" not in existing_tables:
        op.create_table(
            "patient_identifiers",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("patient_id", sa.String(length=36), nullable=False),
            sa.Column("identifier_type", sa.String(length=64), nullable=False),
            sa.Column("value", sa.String(length=128), nullable=False),
            sa.Column("issuing_authority", sa.String(length=128), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("issuing_authority", "value", "identifier_type", name="uq_authority_identifier"),
        )
        op.create_index("ix_patient_identifiers_patient_id", "patient_identifiers", ["patient_id"])
        op.create_index("ix_patient_identifiers_value", "patient_identifiers", ["value"])

    # 4. Clinical Records
    if "clinical_records" not in existing_tables:
        op.create_table(
            "clinical_records",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("job_id", sa.String(length=36), nullable=False),
            sa.Column("patient_id", sa.String(length=36), nullable=True),
            sa.Column("record_type", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("fingerprint", sa.String(length=64), nullable=False),
            sa.Column("source_record_id", sa.String(length=128), nullable=True),
            sa.Column("record_date", sa.String(length=64), nullable=True),
            sa.Column("original_record_date", sa.String(length=64), nullable=True),
            sa.Column("cleaned_text", sa.Text(), nullable=True),
            sa.Column("original_content", sa.Text(), nullable=True),
            sa.Column("parsed_payload", sa.JSON(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("validation_errors", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["ingestion_jobs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_clinical_records_job_id", "clinical_records", ["job_id"])
        op.create_index("ix_clinical_records_patient_id", "clinical_records", ["patient_id"])
        op.create_index("ix_clinical_records_record_type", "clinical_records", ["record_type"])
        op.create_index("ix_clinical_records_status", "clinical_records", ["status"])
        op.create_index("ix_clinical_records_source_record_id", "clinical_records", ["source_record_id"])
        op.create_index("ix_record_job_status", "clinical_records", ["job_id", "status"])
        op.create_index("ix_record_fingerprint", "clinical_records", ["fingerprint"])

    # 5. Audit Logs
    if "audit_logs" not in existing_tables:
        op.create_table(
            "audit_logs",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("job_id", sa.String(length=36), nullable=False),
            sa.Column("record_id", sa.String(length=36), nullable=True),
            sa.Column("field_name", sa.String(length=64), nullable=True),
            sa.Column("original_value", sa.Text(), nullable=True),
            sa.Column("normalized_value", sa.Text(), nullable=True),
            sa.Column("transformation_applied", sa.String(length=128), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("component", sa.String(length=64), nullable=False),
            sa.Column("outcome", sa.String(length=32), nullable=False),
            sa.Column("timestamp", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["ingestion_jobs.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_audit_logs_job_id", "audit_logs", ["job_id"])
        op.create_index("ix_audit_logs_record_id", "audit_logs", ["record_id"])
        op.create_index("ix_audit_logs_timestamp", "audit_logs", ["timestamp"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("clinical_records")
    op.drop_table("patient_identifiers")
    op.drop_table("patients")
    op.drop_table("ingestion_jobs")
