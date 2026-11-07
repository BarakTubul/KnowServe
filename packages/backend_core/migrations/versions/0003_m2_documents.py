"""M2 documents: documents, document_revisions, document_department_access.

Revision ID: 0003
Revises: 0002

Only adds tables, so the previous API and Worker revisions keep working against it (INFRA-05).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


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
    op.create_table(
        "documents",
        _uuid_pk(),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column(
            "owner_department_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("departments.id"),
            nullable=False,
        ),
        sa.Column("current_revision_id", postgresql.UUID(as_uuid=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        _now("created_at"),
        _now("updated_at"),
    )
    op.create_index("ix_documents_owner_department_id", "documents", ["owner_department_id"])
    op.create_index("ix_documents_created_at_id", "documents", ["created_at", "id"])

    op.create_table(
        "document_revisions",
        _uuid_pk(),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("phase", sa.Text()),
        sa.Column("failure_reason", sa.Text()),
        sa.Column("page_count", sa.Integer()),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("embedding_model", sa.Text()),
        sa.Column("index_identity", sa.Text()),
        _now("created_at"),
        sa.Column("ready_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("id", "document_id", name="uq_document_revisions_id_document"),
        sa.CheckConstraint(
            "status IN ('queued','processing','ready','failed')", name="document_revisions_status"
        ),
        sa.CheckConstraint(
            "status <> 'ready' OR (page_count IS NOT NULL AND ready_at IS NOT NULL)",
            name="document_revisions_ready_has_pages",
        ),
        sa.CheckConstraint("page_count IS NULL OR page_count > 0", name="document_revisions_pages"),
        sa.CheckConstraint("size_bytes >= 0", name="document_revisions_size"),
    )
    op.create_index("ix_document_revisions_document_id", "document_revisions", ["document_id"])

    # A current revision must belong to the same document (composite FK; NULL skips the check).
    op.create_foreign_key(
        "fk_documents_current_revision",
        "documents",
        "document_revisions",
        ["current_revision_id", "id"],
        ["id", "document_id"],
    )

    op.create_table(
        "document_department_access",
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "department_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("departments.id"),
            primary_key=True,
        ),
    )
    op.create_index(
        "ix_document_department_access_department_id",
        "document_department_access",
        ["department_id"],
    )


def downgrade() -> None:
    op.drop_table("document_department_access")
    op.drop_constraint("fk_documents_current_revision", "documents", type_="foreignkey")
    op.drop_table("document_revisions")
    op.drop_table("documents")
