"""Add enterprise hybrid RAG indexes, locators and governance audit."""

import sqlalchemy as sa
from alembic import op

revision = "rag_0001"
down_revision = "data_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("knowledge_document_version", sa.Column(
        "parser_name", sa.String(length=64), nullable=False, server_default="legacy_text"
    ))
    op.add_column("knowledge_document_version", sa.Column(
        "parser_version", sa.String(length=32), nullable=False, server_default="legacy"
    ))
    op.add_column("knowledge_document_version", sa.Column(
        "chunking_version", sa.String(length=32), nullable=False, server_default="hybrid-v1"
    ))
    op.add_column("knowledge_document_version", sa.Column(
        "embedding_model", sa.String(length=96), nullable=False,
        server_default="deterministic_multilingual_feature_hash_v1",
    ))
    op.add_column("knowledge_document_version", sa.Column(
        "embedding_dimensions", sa.Integer(), nullable=False, server_default="256"
    ))
    op.add_column("knowledge_document_version", sa.Column(
        "metadata_json", sa.Text(), nullable=False, server_default="{}"
    ))

    op.add_column("knowledge_chunk", sa.Column("paragraph_start", sa.Integer(), nullable=True))
    op.add_column("knowledge_chunk", sa.Column("paragraph_end", sa.Integer(), nullable=True))
    op.add_column("knowledge_chunk", sa.Column(
        "locator_json", sa.Text(), nullable=False, server_default="{}"
    ))

    op.create_table(
        "knowledge_chunk_index",
        sa.Column("chunk_index_id", sa.String(length=64), nullable=False),
        sa.Column("chunk_id", sa.String(length=64), nullable=False),
        sa.Column("embedding_model", sa.String(length=96), nullable=False),
        sa.Column("embedding_version", sa.String(length=32), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("vector_json", sa.Text(), nullable=False),
        sa.Column("vector_norm", sa.Float(), nullable=False),
        sa.Column("term_frequency_json", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["chunk_id"], ["knowledge_chunk.chunk_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("chunk_index_id"),
        sa.UniqueConstraint(
            "chunk_id", "embedding_model", "embedding_version",
            name="uq_knowledge_chunk_embedding_version",
        ),
    )
    op.create_index("ix_knowledge_chunk_index_chunk", "knowledge_chunk_index", ["chunk_id"])
    op.create_index(
        "ix_knowledge_chunk_index_content_sha256", "knowledge_chunk_index", ["content_sha256"]
    )

    op.add_column("knowledge_retrieval_event", sa.Column(
        "rewritten_query_sha256", sa.String(length=64), nullable=True
    ))
    op.add_column("knowledge_retrieval_event", sa.Column(
        "keyword_candidate_count", sa.Integer(), nullable=False, server_default="0"
    ))
    op.add_column("knowledge_retrieval_event", sa.Column(
        "vector_candidate_count", sa.Integer(), nullable=False, server_default="0"
    ))
    op.add_column("knowledge_retrieval_event", sa.Column(
        "injection_rejection_count", sa.Integer(), nullable=False, server_default="0"
    ))
    op.add_column("knowledge_retrieval_event", sa.Column(
        "refusal_reason", sa.String(length=96), nullable=True
    ))
    op.add_column("knowledge_retrieval_event", sa.Column(
        "context_sha256", sa.String(length=64), nullable=True
    ))
    op.add_column("knowledge_retrieval_event", sa.Column(
        "rank_config_json", sa.Text(), nullable=False, server_default="{}"
    ))

    op.create_table(
        "knowledge_governance_event",
        sa.Column("audit_id", sa.String(length=64), nullable=False),
        sa.Column("document_version_id", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.String(length=96), nullable=False),
        sa.Column("actor_type", sa.String(length=24), nullable=False),
        sa.Column("governance_role", sa.String(length=48), nullable=False),
        sa.Column("action", sa.String(length=48), nullable=False),
        sa.Column("reason_code", sa.String(length=96), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("before_json", sa.Text(), nullable=False),
        sa.Column("after_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_version_id"], ["knowledge_document_version.document_version_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("audit_id"),
    )
    op.create_index(
        "ix_knowledge_governance_version_created", "knowledge_governance_event",
        ["document_version_id", "created_at"],
    )
    op.create_index(
        "ix_knowledge_governance_actor_created", "knowledge_governance_event",
        ["actor_type", "actor_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_governance_actor_created", table_name="knowledge_governance_event")
    op.drop_index("ix_knowledge_governance_version_created", table_name="knowledge_governance_event")
    op.drop_table("knowledge_governance_event")

    for column in (
        "rank_config_json", "context_sha256", "refusal_reason",
        "injection_rejection_count", "vector_candidate_count",
        "keyword_candidate_count", "rewritten_query_sha256",
    ):
        op.drop_column("knowledge_retrieval_event", column)

    op.drop_index("ix_knowledge_chunk_index_content_sha256", table_name="knowledge_chunk_index")
    op.drop_index("ix_knowledge_chunk_index_chunk", table_name="knowledge_chunk_index")
    op.drop_table("knowledge_chunk_index")

    for column in ("locator_json", "paragraph_end", "paragraph_start"):
        op.drop_column("knowledge_chunk", column)
    for column in (
        "metadata_json", "embedding_dimensions", "embedding_model",
        "chunking_version", "parser_version", "parser_name",
    ):
        op.drop_column("knowledge_document_version", column)
