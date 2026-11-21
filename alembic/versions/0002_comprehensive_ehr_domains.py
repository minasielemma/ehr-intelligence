"""Add comprehensive healthcare domain tables, relationships, and package tracking.

Revision ID: 0002_comprehensive_ehr_domains
Revises: 0001_initial_schema
Create Date: 2026-11-21 12:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_comprehensive_ehr_domains"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # 1. Organizations
    if "organizations" not in existing_tables:
        op.create_table(
            "organizations",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("source_system", sa.String(length=128), nullable=False),
            sa.Column("source_id", sa.String(length=128), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("org_type", sa.String(length=64), nullable=True),
            sa.Column("address", sa.JSON(), nullable=True),
            sa.Column("phone", sa.String(length=64), nullable=True),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_organizations_source_system", "organizations", ["source_system"])
        op.create_index("ix_organizations_source_id", "organizations", ["source_id"])
        op.create_index("ix_org_source_id", "organizations", ["source_system", "source_id"])

    # 2. Practitioners
    if "practitioners" not in existing_tables:
        op.create_table(
            "practitioners",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("source_system", sa.String(length=128), nullable=False),
            sa.Column("source_id", sa.String(length=128), nullable=False),
            sa.Column("npi", sa.String(length=32), nullable=True),
            sa.Column("first_name", sa.String(length=128), nullable=False),
            sa.Column("last_name", sa.String(length=128), nullable=False),
            sa.Column("specialty", sa.String(length=128), nullable=True),
            sa.Column("email", sa.String(length=128), nullable=True),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_practitioners_source_system", "practitioners", ["source_system"])
        op.create_index("ix_practitioners_source_id", "practitioners", ["source_id"])
        op.create_index("ix_practitioners_npi", "practitioners", ["npi"])
        op.create_index("ix_practitioner_source_id", "practitioners", ["source_system", "source_id"])

    # 3. Encounters
    if "encounters" not in existing_tables:
        op.create_table(
            "encounters",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("job_id", sa.String(length=36), nullable=False),
            sa.Column("source_system", sa.String(length=128), nullable=False),
            sa.Column("source_id", sa.String(length=128), nullable=False),
            sa.Column("patient_id", sa.String(length=36), nullable=False),
            sa.Column("practitioner_id", sa.String(length=36), nullable=True),
            sa.Column("organization_id", sa.String(length=36), nullable=True),
            sa.Column("encounter_class", sa.String(length=32), nullable=False),
            sa.Column("encounter_type", sa.String(length=128), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("start_date", sa.String(length=64), nullable=True),
            sa.Column("end_date", sa.String(length=64), nullable=True),
            sa.Column("reason_code", sa.String(length=64), nullable=True),
            sa.Column("reason_display", sa.String(length=255), nullable=True),
            sa.Column("service_provider", sa.String(length=128), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["ingestion_jobs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["practitioner_id"], ["practitioners.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_encounters_job_id", "encounters", ["job_id"])
        op.create_index("ix_encounters_source_system", "encounters", ["source_system"])
        op.create_index("ix_encounters_source_id", "encounters", ["source_id"])
        op.create_index("ix_encounters_patient_id", "encounters", ["patient_id"])
        op.create_index("ix_encounters_practitioner_id", "encounters", ["practitioner_id"])
        op.create_index("ix_encounters_organization_id", "encounters", ["organization_id"])
        op.create_index("ix_encounters_encounter_class", "encounters", ["encounter_class"])
        op.create_index("ix_encounters_status", "encounters", ["status"])
        op.create_index("ix_encounters_start_date", "encounters", ["start_date"])
        op.create_index("ix_encounter_source_patient", "encounters", ["source_system", "source_id", "patient_id"])

    # 4. Conditions
    if "conditions" not in existing_tables:
        op.create_table(
            "conditions",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("job_id", sa.String(length=36), nullable=False),
            sa.Column("source_system", sa.String(length=128), nullable=False),
            sa.Column("source_id", sa.String(length=128), nullable=True),
            sa.Column("patient_id", sa.String(length=36), nullable=False),
            sa.Column("encounter_id", sa.String(length=36), nullable=True),
            sa.Column("code", sa.String(length=64), nullable=False),
            sa.Column("code_system", sa.String(length=128), nullable=False),
            sa.Column("display", sa.String(length=255), nullable=False),
            sa.Column("clinical_status", sa.String(length=32), nullable=False),
            sa.Column("verification_status", sa.String(length=32), nullable=False),
            sa.Column("severity", sa.String(length=32), nullable=True),
            sa.Column("onset_date", sa.String(length=64), nullable=True),
            sa.Column("recorded_date", sa.String(length=64), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["ingestion_jobs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["encounter_id"], ["encounters.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_conditions_job_id", "conditions", ["job_id"])
        op.create_index("ix_conditions_patient_id", "conditions", ["patient_id"])
        op.create_index("ix_conditions_encounter_id", "conditions", ["encounter_id"])
        op.create_index("ix_conditions_code", "conditions", ["code"])
        op.create_index("ix_conditions_clinical_status", "conditions", ["clinical_status"])
        op.create_index("ix_condition_patient_code", "conditions", ["patient_id", "code"])

    # 5. Observations
    if "observations" not in existing_tables:
        op.create_table(
            "observations",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("job_id", sa.String(length=36), nullable=False),
            sa.Column("source_system", sa.String(length=128), nullable=False),
            sa.Column("source_id", sa.String(length=128), nullable=True),
            sa.Column("patient_id", sa.String(length=36), nullable=False),
            sa.Column("encounter_id", sa.String(length=36), nullable=True),
            sa.Column("category", sa.String(length=64), nullable=False),
            sa.Column("code", sa.String(length=64), nullable=False),
            sa.Column("code_system", sa.String(length=128), nullable=False),
            sa.Column("display", sa.String(length=255), nullable=False),
            sa.Column("value_numeric", sa.Float(), nullable=True),
            sa.Column("value_string", sa.String(length=255), nullable=True),
            sa.Column("unit", sa.String(length=32), nullable=True),
            sa.Column("reference_range_low", sa.Float(), nullable=True),
            sa.Column("reference_range_high", sa.Float(), nullable=True),
            sa.Column("interpretation", sa.String(length=32), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("effective_date", sa.String(length=64), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["ingestion_jobs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["encounter_id"], ["encounters.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_observations_job_id", "observations", ["job_id"])
        op.create_index("ix_observations_patient_id", "observations", ["patient_id"])
        op.create_index("ix_observations_encounter_id", "observations", ["encounter_id"])
        op.create_index("ix_observations_category", "observations", ["category"])
        op.create_index("ix_observations_code", "observations", ["code"])
        op.create_index("ix_observations_effective_date", "observations", ["effective_date"])
        op.create_index("ix_observation_patient_code", "observations", ["patient_id", "code"])
        op.create_index("ix_observation_category_patient", "observations", ["category", "patient_id"])

    # 6. Medication Requests
    if "medication_requests" not in existing_tables:
        op.create_table(
            "medication_requests",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("job_id", sa.String(length=36), nullable=False),
            sa.Column("source_system", sa.String(length=128), nullable=False),
            sa.Column("source_id", sa.String(length=128), nullable=True),
            sa.Column("patient_id", sa.String(length=36), nullable=False),
            sa.Column("encounter_id", sa.String(length=36), nullable=True),
            sa.Column("practitioner_id", sa.String(length=36), nullable=True),
            sa.Column("code", sa.String(length=64), nullable=False),
            sa.Column("code_system", sa.String(length=128), nullable=False),
            sa.Column("display", sa.String(length=255), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("intent", sa.String(length=32), nullable=False),
            sa.Column("dosage_instruction", sa.Text(), nullable=True),
            sa.Column("route", sa.String(length=64), nullable=True),
            sa.Column("dose_quantity", sa.Float(), nullable=True),
            sa.Column("dose_unit", sa.String(length=32), nullable=True),
            sa.Column("frequency", sa.String(length=64), nullable=True),
            sa.Column("authored_on", sa.String(length=64), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["ingestion_jobs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["encounter_id"], ["encounters.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["practitioner_id"], ["practitioners.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_medication_requests_job_id", "medication_requests", ["job_id"])
        op.create_index("ix_medication_requests_patient_id", "medication_requests", ["patient_id"])
        op.create_index("ix_medication_requests_encounter_id", "medication_requests", ["encounter_id"])
        op.create_index("ix_medication_requests_code", "medication_requests", ["code"])
        op.create_index("ix_med_request_patient_code", "medication_requests", ["patient_id", "code"])

    # 7. Medication Administrations
    if "medication_administrations" not in existing_tables:
        op.create_table(
            "medication_administrations",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("job_id", sa.String(length=36), nullable=False),
            sa.Column("source_system", sa.String(length=128), nullable=False),
            sa.Column("source_id", sa.String(length=128), nullable=True),
            sa.Column("patient_id", sa.String(length=36), nullable=False),
            sa.Column("encounter_id", sa.String(length=36), nullable=True),
            sa.Column("medication_request_id", sa.String(length=36), nullable=True),
            sa.Column("code", sa.String(length=64), nullable=False),
            sa.Column("display", sa.String(length=255), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("dosage_administered", sa.Float(), nullable=True),
            sa.Column("unit", sa.String(length=32), nullable=True),
            sa.Column("route", sa.String(length=64), nullable=True),
            sa.Column("effective_date", sa.String(length=64), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["ingestion_jobs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["encounter_id"], ["encounters.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["medication_request_id"], ["medication_requests.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_med_admin_job_id", "medication_administrations", ["job_id"])
        op.create_index("ix_med_admin_patient_id", "medication_administrations", ["patient_id"])
        op.create_index("ix_med_admin_med_req_id", "medication_administrations", ["medication_request_id"])

    # 8. Procedures
    if "procedures" not in existing_tables:
        op.create_table(
            "procedures",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("job_id", sa.String(length=36), nullable=False),
            sa.Column("source_system", sa.String(length=128), nullable=False),
            sa.Column("source_id", sa.String(length=128), nullable=True),
            sa.Column("patient_id", sa.String(length=36), nullable=False),
            sa.Column("encounter_id", sa.String(length=36), nullable=True),
            sa.Column("code", sa.String(length=64), nullable=False),
            sa.Column("code_system", sa.String(length=128), nullable=False),
            sa.Column("display", sa.String(length=255), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("performed_date", sa.String(length=64), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["ingestion_jobs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["encounter_id"], ["encounters.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_procedures_job_id", "procedures", ["job_id"])
        op.create_index("ix_procedures_patient_id", "procedures", ["patient_id"])
        op.create_index("ix_procedures_encounter_id", "procedures", ["encounter_id"])
        op.create_index("ix_procedures_code", "procedures", ["code"])

    # 9. Allergy Intolerances
    if "allergy_intolerances" not in existing_tables:
        op.create_table(
            "allergy_intolerances",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("job_id", sa.String(length=36), nullable=False),
            sa.Column("source_system", sa.String(length=128), nullable=False),
            sa.Column("source_id", sa.String(length=128), nullable=True),
            sa.Column("patient_id", sa.String(length=36), nullable=False),
            sa.Column("clinical_status", sa.String(length=32), nullable=False),
            sa.Column("verification_status", sa.String(length=32), nullable=False),
            sa.Column("allergy_type", sa.String(length=32), nullable=True),
            sa.Column("category", sa.String(length=32), nullable=True),
            sa.Column("criticality", sa.String(length=32), nullable=True),
            sa.Column("code", sa.String(length=64), nullable=True),
            sa.Column("display", sa.String(length=255), nullable=False),
            sa.Column("recorded_date", sa.String(length=64), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["ingestion_jobs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_allergies_job_id", "allergy_intolerances", ["job_id"])
        op.create_index("ix_allergies_patient_id", "allergy_intolerances", ["patient_id"])

    # 10. Immunizations
    if "immunizations" not in existing_tables:
        op.create_table(
            "immunizations",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("job_id", sa.String(length=36), nullable=False),
            sa.Column("source_system", sa.String(length=128), nullable=False),
            sa.Column("source_id", sa.String(length=128), nullable=True),
            sa.Column("patient_id", sa.String(length=36), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("vaccine_code", sa.String(length=64), nullable=False),
            sa.Column("vaccine_display", sa.String(length=255), nullable=False),
            sa.Column("occurrence_date", sa.String(length=64), nullable=True),
            sa.Column("primary_source", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("lot_number", sa.String(length=64), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["ingestion_jobs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_immunizations_job_id", "immunizations", ["job_id"])
        op.create_index("ix_immunizations_patient_id", "immunizations", ["patient_id"])
        op.create_index("ix_immunizations_vaccine_code", "immunizations", ["vaccine_code"])

    # 11. Coverages
    if "coverages" not in existing_tables:
        op.create_table(
            "coverages",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("job_id", sa.String(length=36), nullable=False),
            sa.Column("source_system", sa.String(length=128), nullable=False),
            sa.Column("source_id", sa.String(length=128), nullable=True),
            sa.Column("patient_id", sa.String(length=36), nullable=False),
            sa.Column("subscriber_id", sa.String(length=128), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("coverage_type", sa.String(length=64), nullable=True),
            sa.Column("payer_name", sa.String(length=128), nullable=False),
            sa.Column("relationship_to_subscriber", sa.String(length=32), nullable=True),
            sa.Column("period_start", sa.String(length=64), nullable=True),
            sa.Column("period_end", sa.String(length=64), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["ingestion_jobs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_coverages_job_id", "coverages", ["job_id"])
        op.create_index("ix_coverages_patient_id", "coverages", ["patient_id"])

    # 12. Claims
    if "claims" not in existing_tables:
        op.create_table(
            "claims",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("job_id", sa.String(length=36), nullable=False),
            sa.Column("source_system", sa.String(length=128), nullable=False),
            sa.Column("source_id", sa.String(length=128), nullable=True),
            sa.Column("patient_id", sa.String(length=36), nullable=False),
            sa.Column("encounter_id", sa.String(length=36), nullable=True),
            sa.Column("coverage_id", sa.String(length=36), nullable=True),
            sa.Column("claim_type", sa.String(length=32), nullable=False),
            sa.Column("use", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("total_amount", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("currency", sa.String(length=16), nullable=False, server_default="USD"),
            sa.Column("created_date", sa.String(length=64), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["ingestion_jobs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["encounter_id"], ["encounters.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["coverage_id"], ["coverages.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_claims_job_id", "claims", ["job_id"])
        op.create_index("ix_claims_patient_id", "claims", ["patient_id"])
        op.create_index("ix_claims_encounter_id", "claims", ["encounter_id"])

    # 13. Care Plans
    if "care_plans" not in existing_tables:
        op.create_table(
            "care_plans",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("job_id", sa.String(length=36), nullable=False),
            sa.Column("source_system", sa.String(length=128), nullable=False),
            sa.Column("source_id", sa.String(length=128), nullable=True),
            sa.Column("patient_id", sa.String(length=36), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("intent", sa.String(length=32), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("period_start", sa.String(length=64), nullable=True),
            sa.Column("period_end", sa.String(length=64), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["ingestion_jobs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_care_plans_job_id", "care_plans", ["job_id"])
        op.create_index("ix_care_plans_patient_id", "care_plans", ["patient_id"])

    # 14. Consents
    if "consents" not in existing_tables:
        op.create_table(
            "consents",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("job_id", sa.String(length=36), nullable=False),
            sa.Column("source_system", sa.String(length=128), nullable=False),
            sa.Column("source_id", sa.String(length=128), nullable=True),
            sa.Column("patient_id", sa.String(length=36), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("scope", sa.String(length=64), nullable=False),
            sa.Column("category", sa.String(length=64), nullable=True),
            sa.Column("date_time", sa.String(length=64), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["ingestion_jobs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_consents_job_id", "consents", ["job_id"])
        op.create_index("ix_consents_patient_id", "consents", ["patient_id"])

    # 15. Service Requests
    if "service_requests" not in existing_tables:
        op.create_table(
            "service_requests",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("job_id", sa.String(length=36), nullable=False),
            sa.Column("source_system", sa.String(length=128), nullable=False),
            sa.Column("source_id", sa.String(length=128), nullable=True),
            sa.Column("patient_id", sa.String(length=36), nullable=False),
            sa.Column("encounter_id", sa.String(length=36), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("intent", sa.String(length=32), nullable=False),
            sa.Column("code", sa.String(length=64), nullable=False),
            sa.Column("display", sa.String(length=255), nullable=False),
            sa.Column("authored_on", sa.String(length=64), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["ingestion_jobs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["encounter_id"], ["encounters.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_service_requests_job_id", "service_requests", ["job_id"])
        op.create_index("ix_service_requests_patient_id", "service_requests", ["patient_id"])

    # 16. Diagnostic Reports
    if "diagnostic_reports" not in existing_tables:
        op.create_table(
            "diagnostic_reports",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("job_id", sa.String(length=36), nullable=False),
            sa.Column("source_system", sa.String(length=128), nullable=False),
            sa.Column("source_id", sa.String(length=128), nullable=True),
            sa.Column("patient_id", sa.String(length=36), nullable=False),
            sa.Column("encounter_id", sa.String(length=36), nullable=True),
            sa.Column("service_request_id", sa.String(length=36), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("category", sa.String(length=64), nullable=False),
            sa.Column("code", sa.String(length=64), nullable=False),
            sa.Column("display", sa.String(length=255), nullable=False),
            sa.Column("effective_date", sa.String(length=64), nullable=True),
            sa.Column("conclusion", sa.Text(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["ingestion_jobs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["encounter_id"], ["encounters.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["service_request_id"], ["service_requests.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_diag_reports_job_id", "diagnostic_reports", ["job_id"])
        op.create_index("ix_diag_reports_patient_id", "diagnostic_reports", ["patient_id"])

    # 17. Imaging Studies
    if "imaging_studies" not in existing_tables:
        op.create_table(
            "imaging_studies",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("job_id", sa.String(length=36), nullable=False),
            sa.Column("source_system", sa.String(length=128), nullable=False),
            sa.Column("source_id", sa.String(length=128), nullable=True),
            sa.Column("patient_id", sa.String(length=36), nullable=False),
            sa.Column("encounter_id", sa.String(length=36), nullable=True),
            sa.Column("modality", sa.String(length=32), nullable=False),
            sa.Column("description", sa.String(length=255), nullable=True),
            sa.Column("started_date", sa.String(length=64), nullable=True),
            sa.Column("number_of_series", sa.Integer(), nullable=True, server_default="1"),
            sa.Column("number_of_instances", sa.Integer(), nullable=True, server_default="1"),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["ingestion_jobs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["encounter_id"], ["encounters.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_imaging_studies_job_id", "imaging_studies", ["job_id"])
        op.create_index("ix_imaging_studies_patient_id", "imaging_studies", ["patient_id"])

    # 18. Document References
    if "document_references" not in existing_tables:
        op.create_table(
            "document_references",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("job_id", sa.String(length=36), nullable=False),
            sa.Column("source_system", sa.String(length=128), nullable=False),
            sa.Column("source_id", sa.String(length=128), nullable=True),
            sa.Column("patient_id", sa.String(length=36), nullable=False),
            sa.Column("encounter_id", sa.String(length=36), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("doc_type", sa.String(length=64), nullable=False),
            sa.Column("category", sa.String(length=64), nullable=True),
            sa.Column("date", sa.String(length=64), nullable=True),
            sa.Column("description", sa.String(length=255), nullable=True),
            sa.Column("content_text", sa.Text(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["ingestion_jobs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["encounter_id"], ["encounters.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_doc_refs_job_id", "document_references", ["job_id"])
        op.create_index("ix_doc_refs_patient_id", "document_references", ["patient_id"])

    # 19. Provenances
    if "provenances" not in existing_tables:
        op.create_table(
            "provenances",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("job_id", sa.String(length=36), nullable=False),
            sa.Column("source_system", sa.String(length=128), nullable=False),
            sa.Column("target_resource_type", sa.String(length=64), nullable=False),
            sa.Column("target_resource_id", sa.String(length=128), nullable=False),
            sa.Column("recorded_at", sa.DateTime(), nullable=False),
            sa.Column("activity", sa.String(length=64), nullable=False),
            sa.Column("agent_name", sa.String(length=128), nullable=True),
            sa.Column("agent_role", sa.String(length=64), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["job_id"], ["ingestion_jobs.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_provenances_job_id", "provenances", ["job_id"])
        op.create_index("ix_provenances_target", "provenances", ["target_resource_type", "target_resource_id"])

    # 20. Package Files
    if "package_files" not in existing_tables:
        op.create_table(
            "package_files",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("job_id", sa.String(length=36), nullable=False),
            sa.Column("file_path", sa.String(length=255), nullable=False),
            sa.Column("domain", sa.String(length=64), nullable=False),
            sa.Column("format", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("total_records", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("successful_records", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("rejected_records", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["job_id"], ["ingestion_jobs.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_package_files_job_id", "package_files", ["job_id"])
        op.create_index("ix_package_files_domain", "package_files", ["domain"])
        op.create_index("ix_package_files_status", "package_files", ["status"])

    # 21. Alter clinical_records to add encounter_id if missing
    if "clinical_records" in existing_tables:
        columns = [c["name"] for c in inspector.get_columns("clinical_records")]
        if "encounter_id" not in columns:
            with op.batch_alter_table("clinical_records") as batch_op:
                batch_op.add_column(sa.Column("encounter_id", sa.String(length=36), nullable=True))
                batch_op.create_foreign_key(
                    "fk_clinical_records_encounter_id",
                    "encounters",
                    ["encounter_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
                batch_op.create_index("ix_record_encounter", ["encounter_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    if "clinical_records" in existing_tables:
        columns = [c["name"] for c in inspector.get_columns("clinical_records")]
        if "encounter_id" in columns:
            with op.batch_alter_table("clinical_records") as batch_op:
                batch_op.drop_index("ix_record_encounter")
                batch_op.drop_column("encounter_id")

    for tbl in [
        "package_files",
        "provenances",
        "document_references",
        "imaging_studies",
        "diagnostic_reports",
        "service_requests",
        "consents",
        "care_plans",
        "claims",
        "coverages",
        "immunizations",
        "allergy_intolerances",
        "procedures",
        "medication_administrations",
        "medication_requests",
        "observations",
        "conditions",
        "encounters",
        "practitioners",
        "organizations",
    ]:
        if tbl in existing_tables:
            op.drop_table(tbl)
