"""Add governed enterprise knowledge lifecycle and retrieval evidence."""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_document",
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("scenario_id", sa.String(length=64), nullable=False),
        sa.Column("knowledge_domain", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("source_path", sa.String(length=1024), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.String(length=96), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("document_id"),
    )
    op.create_index(
        "ix_knowledge_document_scope",
        "knowledge_document",
        ["tenant_id", "workspace_id", "scenario_id", "knowledge_domain"],
    )
    op.create_table(
        "knowledge_document_version",
        sa.Column("document_version_id", sa.String(length=64), nullable=False),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("raw_content", sa.Text(), nullable=False),
        sa.Column("normalized_content", sa.Text(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("supersedes_version_id", sa.String(length=64), nullable=True),
        sa.Column("failure_reason", sa.String(length=512), nullable=True),
        sa.Column("created_by", sa.String(length=96), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["knowledge_document.document_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("document_version_id"),
        sa.UniqueConstraint("document_id", "version", name="uq_knowledge_document_version"),
    )
    op.create_index(
        "ix_knowledge_document_version_document_id",
        "knowledge_document_version",
        ["document_id"],
    )
    op.create_index(
        "ix_knowledge_document_version_content_sha256",
        "knowledge_document_version",
        ["content_sha256"],
    )
    op.create_index(
        "ix_knowledge_document_version_status",
        "knowledge_document_version",
        ["status"],
    )
    op.create_index(
        "ix_knowledge_version_status_validity",
        "knowledge_document_version",
        ["status", "valid_from", "valid_to"],
    )
    op.create_table(
        "knowledge_document_acl",
        sa.Column("acl_id", sa.String(length=64), nullable=False),
        sa.Column("document_version_id", sa.String(length=64), nullable=False),
        sa.Column("principal_type", sa.String(length=24), nullable=False),
        sa.Column("principal_value", sa.String(length=96), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["knowledge_document_version.document_version_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("acl_id"),
        sa.UniqueConstraint(
            "document_version_id",
            "principal_type",
            "principal_value",
            name="uq_knowledge_document_acl",
        ),
    )
    op.create_index(
        "ix_knowledge_acl_lookup",
        "knowledge_document_acl",
        ["principal_type", "principal_value", "document_version_id"],
    )
    op.create_table(
        "knowledge_chunk",
        sa.Column("chunk_id", sa.String(length=64), nullable=False),
        sa.Column("document_version_id", sa.String(length=64), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(length=256), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["knowledge_document_version.document_version_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("chunk_id"),
        sa.UniqueConstraint(
            "document_version_id",
            "ordinal",
            name="uq_knowledge_chunk_ordinal",
        ),
    )
    op.create_index(
        "ix_knowledge_chunk_content_sha256",
        "knowledge_chunk",
        ["content_sha256"],
    )
    op.create_index(
        "ix_knowledge_chunk_version",
        "knowledge_chunk",
        ["document_version_id", "ordinal"],
    )
    op.create_table(
        "knowledge_publication_event",
        sa.Column("publication_event_id", sa.String(length=64), nullable=False),
        sa.Column("document_version_id", sa.String(length=64), nullable=False),
        sa.Column("previous_version_id", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column("actor_id", sa.String(length=96), nullable=False),
        sa.Column("reason", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["knowledge_document_version.document_version_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("publication_event_id"),
    )
    op.create_index(
        "ix_knowledge_publication_version_created",
        "knowledge_publication_event",
        ["document_version_id", "created_at"],
    )
    op.create_table(
        "knowledge_retrieval_event",
        sa.Column("retrieval_event_id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("scenario_id", sa.String(length=64), nullable=False),
        sa.Column("subject_id", sa.String(length=96), nullable=False),
        sa.Column("query_sha256", sa.String(length=64), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("retrieval_mode", sa.String(length=32), nullable=False),
        sa.Column("vector_status", sa.String(length=32), nullable=False),
        sa.Column("cited_chunk_ids_json", sa.Text(), nullable=False),
        sa.Column("trace_id", sa.String(length=96), nullable=False),
        sa.Column("run_id", sa.String(length=96), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("retrieval_event_id"),
    )
    op.create_index(
        "ix_knowledge_retrieval_event_trace_id",
        "knowledge_retrieval_event",
        ["trace_id"],
    )
    op.create_index(
        "ix_knowledge_retrieval_event_run_id",
        "knowledge_retrieval_event",
        ["run_id"],
    )
    op.create_index(
        "ix_knowledge_retrieval_scope_created",
        "knowledge_retrieval_event",
        ["tenant_id", "workspace_id", "scenario_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("knowledge_retrieval_event")
    op.drop_table("knowledge_publication_event")
    op.drop_table("knowledge_chunk")
    op.drop_table("knowledge_document_acl")
    op.drop_table("knowledge_document_version")
    op.drop_table("knowledge_document")
