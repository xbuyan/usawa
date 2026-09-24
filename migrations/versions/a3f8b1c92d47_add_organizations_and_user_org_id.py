"""Add organizations table and users.organization_id (org/team sharing)

Revision ID: a3f8b1c92d47
Revises: d5e7a3b1c9f2
Create Date: 2026-09-24

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a3f8b1c92d47"
down_revision = "d5e7a3b1c9f2"
branch_labels = None
depends_on = None


def upgrade():
    # --- organizations table ------------------------------------------
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # --- users.organization_id, added nullable first -------------------
    # Every user must end up with exactly one Organization, but there's
    # no single constant value that's correct for every existing user —
    # unlike email_verified or share_anonymized_data (both backfilled via
    # a fixed server_default; see those migrations and PROJECT_STATUS.md
    # for the production incident that taught that lesson). This needs a
    # freshly created, distinct Organization per existing user, so the
    # column is added nullable first, backfilled row by row below, and
    # only then tightened to NOT NULL. Skipping the nullable-first step
    # would fail immediately against any table with existing rows — the
    # exact class of incident that already happened once in this project.
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("organization_id", sa.Integer(), nullable=True))

    bind = op.get_bind()

    # Reflected as plain sa.table()/sa.column() objects, not imported from
    # models.py — a migration should describe the schema as it existed
    # at the moment it was written, not however models.py happens to look
    # by the time this migration runs (which, months later, may not match).
    organizations = sa.table(
        "organizations",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("created_at", sa.DateTime),
    )
    users = sa.table(
        "users",
        sa.column("id", sa.Integer),
        sa.column("email", sa.String),
        sa.column("organization_name", sa.String),
        sa.column("organization_id", sa.Integer),
    )

    existing_users = bind.execute(
        sa.select(users.c.id, users.c.email, users.c.organization_name).order_by(users.c.id)
    ).fetchall()

    for row in existing_users:
        # organization_name was always optional free text collected at
        # signup — reuse it as the new Organization's name where a user
        # gave one; fall back to something derived from their email
        # rather than a bare "Untitled", so the backfilled name still
        # means something to that user when they see it in the product.
        org_name = row.organization_name or f"{row.email}'s organization"

        # .returning(), deliberately not cursor.lastrowid or a follow-up
        # "ORDER BY id DESC LIMIT 1" query: lastrowid only ever reflects
        # the single most recently executed insert on the connection, and
        # a re-query by descending id is exactly the kind of assumption
        # that's silently wrong the moment this migration's insert order
        # isn't the same as this loop's insert order (or if anything else
        # touches the table mid-migration). .returning() ties the new id
        # directly to the insert that produced it, with no such assumption.
        result = bind.execute(
            sa.insert(organizations).values(name=org_name).returning(organizations.c.id)
        )
        new_org_id = result.scalar_one()

        bind.execute(
            sa.update(users).where(users.c.id == row.id).values(organization_id=new_org_id)
        )

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column("organization_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key(
            "fk_users_organization_id", "organizations", ["organization_id"], ["id"]
        )
        batch_op.create_index("ix_users_organization_id", ["organization_id"])


def downgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index("ix_users_organization_id")
        batch_op.drop_constraint("fk_users_organization_id", type_="foreignkey")
        batch_op.drop_column("organization_id")

    op.drop_table("organizations")
