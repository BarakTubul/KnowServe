"""M0 initial schema: pgvector extension, jobs, outbox, vector probe.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("claimed_by", sa.Text()),
        sa.Column("correlation_id", sa.Text(), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('queued','processing','done','failed')", name="jobs_status"),
    )

    op.create_table(
        "outbox",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("correlation_id", sa.Text(), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("status IN ('pending','published')", name="outbox_status"),
    )
    op.create_index("ix_outbox_status_next_attempt", "outbox", ["status", "next_attempt_at"])

    op.create_table(
        "spike_vector_probe",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("embedding", Vector(8), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("spike_vector_probe")
    op.drop_index("ix_outbox_status_next_attempt", table_name="outbox")
    op.drop_table("outbox")
    op.drop_table("jobs")
    # The vector extension is intentionally left installed: other schemas may use it.
