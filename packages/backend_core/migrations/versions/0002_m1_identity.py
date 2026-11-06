"""M1 identity schema: departments (seeded), users, sessions, audit, counters.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# Stable ids (uuid5 of the slug) so every environment shares them (D6, AUTH-20).
DEPARTMENTS = [
    ("5bb20871-4372-57f0-9e45-9e20db142d70", "human-resources", "Human Resources", 1),
    ("4f3257da-409f-5643-b889-67eea4d34f21", "finance", "Finance", 2),
    ("2785b8aa-6102-5d05-b400-0fb9de71b614", "engineering", "Engineering", 3),
    ("3174db2f-1584-5ddb-8fbd-60b4157086d3", "legal", "Legal", 4),
    ("5e306cf1-a61b-54b2-ade8-717f9ff783b0", "sales", "Sales", 5),
]


def _uuid_pk() -> sa.Column:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )


def _now(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    departments = op.create_table(
        "departments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
    )
    op.bulk_insert(
        departments,
        [{"id": i, "slug": s, "name": n, "position": p} for i, s, n, p in DEPARTMENTS],
    )

    op.create_table(
        "users",
        _uuid_pk(),
        sa.Column("firebase_uid", sa.Text(), nullable=False, unique=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("email", sa.Text()),
        sa.Column("display_name", sa.Text()),
        sa.Column(
            "last_active_department_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("departments.id"),
        ),
        sa.Column("disabled_at", sa.DateTime(timezone=True)),
        sa.Column("converted_at", sa.DateTime(timezone=True)),
        _now("created_at"),
        _now("updated_at"),
        sa.CheckConstraint("kind IN ('demo','registered','admin')", name="users_kind"),
    )
    op.create_index(
        "uq_users_email",
        "users",
        ["email"],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )
    op.create_index("ix_users_kind_created_at", "users", ["kind", "created_at"])

    op.create_table(
        "sessions",
        _uuid_pk(),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sign_in_provider", sa.Text(), nullable=False),
        sa.Column(
            "active_department_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("departments.id")
        ),
        sa.Column("csrf_secret", sa.Text(), nullable=False),
        _now("created_at"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])

    op.create_table(
        "audit_events",
        _uuid_pk(),
        _now("occurred_at"),
        sa.Column("event", sa.Text(), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("request_id", sa.Text()),
        sa.Column("ip", sa.Text()),
        sa.Column(
            "details",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"])

    op.create_table(
        "rate_limit_counters",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "usage_counters",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("metric", sa.Text(), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "ai_usage_daily",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("used", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    for table in (
        "ai_usage_daily",
        "usage_counters",
        "rate_limit_counters",
        "audit_events",
        "sessions",
        "users",
        "departments",
    ):
        op.drop_table(table)
