"""Add learning layer and assistant chat

Revision ID: b4f2c91a7d3e
Revises: e3d0b1ec9184
Create Date: 2026-09-22

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b4f2c91a7d3e"
down_revision = "e3d0b1ec9184"
branch_labels = None
depends_on = None


def upgrade():
    # --- company_snapshots -------------------------------------------------
    # Anonymized by construction: no user_id column exists to join back to
    # an account, and company_name is deliberately not stored here at all.
    op.create_table(
        "company_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("industry", sa.String(length=100), nullable=True),
        sa.Column("size_band", sa.String(length=20), nullable=False),
        sa.Column("overall_score", sa.Integer(), nullable=False),
        sa.Column("pay_equity_score", sa.Integer(), nullable=True),
        sa.Column("promotion_equity_score", sa.Integer(), nullable=True),
        sa.Column("hiring_funnel_score", sa.Integer(), nullable=True),
        sa.Column("representation_score", sa.Integer(), nullable=True),
        sa.Column("job_language_score", sa.Integer(), nullable=True),
        sa.Column("metrics_json", sa.Text(), nullable=False),
        sa.Column("features_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_company_snapshots_industry", "company_snapshots", ["industry"])
    op.create_index("ix_company_snapshots_size_band", "company_snapshots", ["size_band"])
    op.create_index("ix_company_snapshots_created_at", "company_snapshots", ["created_at"])

    # --- benchmark_stats ---------------------------------------------------
    # Precomputed cohort percentiles: one row per cohort x metric x point.
    op.create_table(
        "benchmark_stats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("industry", sa.String(length=100), nullable=True),
        sa.Column("size_band", sa.String(length=20), nullable=False),
        sa.Column("metric", sa.String(length=64), nullable=False),
        sa.Column("n_companies", sa.Integer(), nullable=False),
        sa.Column("percentile", sa.Integer(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_benchmark_cohort_metric",
        "benchmark_stats",
        ["industry", "size_band", "metric", "percentile"],
    )

    # --- learned_patterns --------------------------------------------------
    # Mined cohort correlations ("companies with X hiring practice tend to
    # have Y pay gap"), each carrying its sample size so the UI can show
    # how much data a pattern actually rests on.
    op.create_table(
        "learned_patterns",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("industry", sa.String(length=100), nullable=True),
        sa.Column("size_band", sa.String(length=20), nullable=False),
        sa.Column("condition_metric", sa.String(length=64), nullable=False),
        sa.Column("condition_label", sa.String(length=255), nullable=False),
        sa.Column("outcome_metric", sa.String(64), nullable=False),
        sa.Column("correlation", sa.Float(), nullable=False),
        sa.Column("outcome_delta_median", sa.Float(), nullable=False),
        sa.Column("n_companies", sa.Integer(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_patterns_cohort",
        "learned_patterns",
        ["industry", "size_band", "condition_metric"],
    )

    # --- conversations / chat_messages --------------------------------------
    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sources_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_messages_conversation_id", "chat_messages", ["conversation_id"])

    # --- users.share_anonymized_data ----------------------------------------
    # NOT NULL addition to an existing table: server_default is mandatory
    # (see PROJECT_STATUS.md's production incident — the email_verified
    # migration failed in production for exactly this reason). Backfills
    # existing users to False; the feature is opt-in by default.
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("share_anonymized_data", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("share_anonymized_data")

    op.drop_index("ix_chat_messages_conversation_id", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_conversations_user_id", table_name="conversations")
    op.drop_table("conversations")

    op.drop_index("ix_patterns_cohort", table_name="learned_patterns")
    op.drop_table("learned_patterns")
    op.drop_index("ix_benchmark_cohort_metric", table_name="benchmark_stats")
    op.drop_table("benchmark_stats")

    op.drop_index("ix_company_snapshots_created_at", table_name="company_snapshots")
    op.drop_index("ix_company_snapshots_size_band", table_name="company_snapshots")
    op.drop_index("ix_company_snapshots_industry", table_name="company_snapshots")
    op.drop_table("company_snapshots")
