"""Add seeded flag to company_snapshots

Revision ID: c8a1e4f2b9d5
Revises: b4f2c91a7d3e
Create Date: 2026-09-22

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c8a1e4f2b9d5"
down_revision = "b4f2c91a7d3e"
branch_labels = None
depends_on = None


def upgrade():
    # NOT NULL addition to an existing table: server_default is mandatory
    # (see PROJECT_STATUS.md's production incident). Backfills existing
    # snapshots — which can only be real captures at this point — to False.
    with op.batch_alter_table("company_snapshots", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("seeded", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade():
    with op.batch_alter_table("company_snapshots", schema=None) as batch_op:
        batch_op.drop_column("seeded")
