"""M3 ingestion: chunks, the revision-to-job link, Admin idempotency and import bookkeeping.

Revision ID: 0004
Revises: 0003

Additive only: new tables and one nullable column. The previous API and Worker revisions keep
working against it (INFRA-05), so an application rollback needs no downgrade. There is no vector
index on purpose (OPEN-31 D5): M3 queries chunks with an exact scan, and M4 decides the index.
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

# text-embedding-3-small (ING-18). Changing the dimension needs a new migration and a re-embed.
EMBEDDING_DIMENSIONS = 1536


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
    # A revision is processed by exactly one job (ING-21: the envelope carries only the job id).
    # Seeded revisions (M2) have no job until the reindex run, so the column is nullable.
    op.add_column(
        "document_revisions",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id")),
    )
    op.create_index(
        "uq_document_revisions_job_id",
        "document_revisions",
        ["job_id"],
        unique=True,
        postgresql_where=sa.text("job_id IS NOT NULL"),
    )

    op.create_table(
        "document_chunks",
        _uuid_pk(),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=False),
        _now("created_at"),
        # A chunk belongs to a revision of the same document (composite FK, like the current
        # revision pointer). Hard-deleting a document or revision removes its chunks (M5).
        sa.ForeignKeyConstraint(
            ["revision_id", "document_id"],
            ["document_revisions.id", "document_revisions.document_id"],
            name="fk_document_chunks_revision_document",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("revision_id", "ordinal", name="uq_document_chunks_revision_ordinal"),
        sa.CheckConstraint("page >= 1", name="document_chunks_page"),
        sa.CheckConstraint("ordinal >= 0", name="document_chunks_ordinal"),
        sa.CheckConstraint("token_count >= 1", name="document_chunks_tokens"),
    )
    op.create_index("ix_document_chunks_document_id", "document_chunks", ["document_id"])

    # One row per completed Admin operation. It is written in the same transaction as the
    # document rows it created, so a duplicate request either waits on the unique key and then
    # replays the stored result, or finds nothing and runs once.
    op.create_table(
        "admin_idempotency_keys",
        _uuid_pk(),
        sa.Column(
            "admin_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("result_status", sa.Integer(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        _now("created_at"),
        sa.UniqueConstraint(
            "admin_user_id", "idempotency_key", name="uq_admin_idempotency_user_key"
        ),
        sa.CheckConstraint(
            "operation IN ('create_document','replace_document','confirm_import')",
            name="admin_idempotency_operation",
        ),
        sa.CheckConstraint("char_length(request_hash) = 64", name="admin_idempotency_hash"),
    )

    # Per-entry outcome of a ZIP confirmation. It lets a confirmation that died half way resume
    # under the same key without creating an entry twice (ADM-13, ADM-14).
    op.create_table(
        "import_batch_entries",
        _uuid_pk(),
        sa.Column(
            "idempotency_key_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("admin_idempotency_keys.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entry_key", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id")),
        sa.Column("error_code", sa.Text()),
        _now("created_at"),
        sa.UniqueConstraint(
            "idempotency_key_id", "entry_key", name="uq_import_batch_entries_key_entry"
        ),
        sa.CheckConstraint(
            "outcome IN ('created','rejected')", name="import_batch_entries_outcome"
        ),
        sa.CheckConstraint(
            "(outcome = 'created' AND document_id IS NOT NULL AND error_code IS NULL)"
            " OR (outcome = 'rejected' AND document_id IS NULL AND error_code IS NOT NULL)",
            name="import_batch_entries_shape",
        ),
    )


def downgrade() -> None:
    # Drops every chunk and Admin idempotency record. Never part of an application rollback:
    # take a Neon branch first and decide it on its own (docs/milestones/M3/plan.md section 15).
    op.drop_table("import_batch_entries")
    op.drop_table("admin_idempotency_keys")
    op.drop_table("document_chunks")
    op.drop_index("uq_document_revisions_job_id", table_name="document_revisions")
    op.drop_column("document_revisions", "job_id")
