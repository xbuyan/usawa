"""Add terms_accepted_at to users

Revision ID: d5e7a3b1c9f2
Revises: c8a1e4f2b9d5
Create Date: 2026-09-23

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d5e7a3b1c9f2"
down_revision = "c8a1e4f2b9d5"
branch_labels = None
depends_on = None


def upgrade():
    # Nullable, no server_default, deliberately: existing users never
    # accepted these terms at signup, and NULL is the truthful value for
    # them. Adding a nullable column also can't hit the NOT NULL failure
    # that broke the email_verified migration on a table with real rows.
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("terms_accepted_at", sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("terms_accepted_at")
