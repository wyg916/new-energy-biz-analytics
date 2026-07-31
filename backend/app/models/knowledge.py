from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_document"
    __table_args__ = (
        Index(
            "ix_knowledge_document_scope",
            "tenant_id",
            "workspace_id",
            "scenario_id",
            "knowledge_domain",
        ),
    )

    document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64))
    workspace_id: Mapped[str] = mapped_column(String(64))
    scenario_id: Mapped[str] = mapped_column(String(64))
    knowledge_domain: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(256))
    source_path: Mapped[str] = mapped_column(String(1024))
    source_kind: Mapped[str] = mapped_column(String(32))
    created_by: Mapped[str] = mapped_column(String(96))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class KnowledgeDocumentVersion(Base):
    __tablename__ = "knowledge_document_version"
    __table_args__ = (
        UniqueConstraint("document_id", "version", name="uq_knowledge_document_version"),
        Index("ix_knowledge_version_status_validity", "status", "valid_from", "valid_to"),
    )

    document_version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_document.document_id", ondelete="CASCADE"),
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), index=True)
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    mime_type: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer)
    raw_content: Mapped[str] = mapped_column(Text)
    normalized_content: Mapped[str] = mapped_column(Text)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    supersedes_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_by: Mapped[str] = mapped_column(String(96))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class KnowledgeDocumentAcl(Base):
    __tablename__ = "knowledge_document_acl"
    __table_args__ = (
        UniqueConstraint(
            "document_version_id",
            "principal_type",
            "principal_value",
            name="uq_knowledge_document_acl",
        ),
        Index(
            "ix_knowledge_acl_lookup",
            "principal_type",
            "principal_value",
            "document_version_id",
        ),
    )

    acl_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_document_version.document_version_id", ondelete="CASCADE")
    )
    principal_type: Mapped[str] = mapped_column(String(24))
    principal_value: Mapped[str] = mapped_column(String(96))


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunk"
    __table_args__ = (
        UniqueConstraint("document_version_id", "ordinal", name="uq_knowledge_chunk_ordinal"),
        Index("ix_knowledge_chunk_version", "document_version_id", "ordinal"),
    )

    chunk_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_document_version.document_version_id", ondelete="CASCADE")
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(256), nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    token_estimate: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class KnowledgePublicationEvent(Base):
    __tablename__ = "knowledge_publication_event"
    __table_args__ = (
        Index("ix_knowledge_publication_version_created", "document_version_id", "created_at"),
    )

    publication_event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_document_version.document_version_id", ondelete="CASCADE")
    )
    previous_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(24))
    actor_id: Mapped[str] = mapped_column(String(96))
    reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class KnowledgeRetrievalEvent(Base):
    __tablename__ = "knowledge_retrieval_event"
    __table_args__ = (
        Index(
            "ix_knowledge_retrieval_scope_created",
            "tenant_id",
            "workspace_id",
            "scenario_id",
            "created_at",
        ),
    )

    retrieval_event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64))
    workspace_id: Mapped[str] = mapped_column(String(64))
    scenario_id: Mapped[str] = mapped_column(String(64))
    subject_id: Mapped[str] = mapped_column(String(96))
    query_sha256: Mapped[str] = mapped_column(String(64))
    result_count: Mapped[int] = mapped_column(Integer)
    retrieval_mode: Mapped[str] = mapped_column(String(32))
    vector_status: Mapped[str] = mapped_column(String(32))
    cited_chunk_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    trace_id: Mapped[str] = mapped_column(String(96), index=True)
    run_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    latency_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


KNOWLEDGE_TABLES = [
    KnowledgeDocument.__table__,
    KnowledgeDocumentVersion.__table__,
    KnowledgeDocumentAcl.__table__,
    KnowledgeChunk.__table__,
    KnowledgePublicationEvent.__table__,
    KnowledgeRetrievalEvent.__table__,
]
