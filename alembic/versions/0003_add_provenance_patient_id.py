"""Add patient_id column to provenances table.

Revision ID: 0003_add_provenance_patient_id
Revises: 0002_comprehensive_ehr_domains
Create Date: 2026-11-21 16:11:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0003_add_provenance_patient_id"
down_revision: Union[str, None] = "0002_comprehensive_ehr_domains"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()
    if "provenances" in existing_tables:
        columns = [c["name"] for c in inspector.get_columns("provenances")]
        if "patient_id" not in columns:
            with op.batch_alter_table("provenances") as batch_op:
                batch_op.add_column(sa.Column("patient_id", sa.String(length=36), nullable=True))
                batch_op.create_foreign_key("fk_provenances_patient_id", "patients", ["patient_id"], ["id"], ondelete="CASCADE")
                batch_op.create_index("ix_provenances_patient_id", ["patient_id"])


def downgrade() -> None:
    with op.batch_alter_table("provenances") as batch_op:
        batch_op.drop_index("ix_provenances_patient_id")
        batch_op.drop_constraint("fk_provenances_patient_id", type_="foreignkey")
        batch_op.drop_column("patient_id")
