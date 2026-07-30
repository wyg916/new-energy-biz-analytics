from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    Float,
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


class SQLBotSessionBindingRecord(Base):
    __tablename__ = "sqlbot_session_binding"
    __table_args__ = (
        UniqueConstraint("binding_hash", name="uq_sqlbot_session_binding_hash"),
        Index(
            "ix_sqlbot_session_binding_scope",
            "tenant_id",
            "workspace_id",
            "subject_id",
            "scenario_id",
        ),
    )

    binding_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    binding_hash: Mapped[str] = mapped_column(String(64))
    tenant_id: Mapped[str] = mapped_column(String(64))
    workspace_id: Mapped[str] = mapped_column(String(64))
    subject_id: Mapped[str] = mapped_column(String(96))
    conversation_id: Mapped[str] = mapped_column(String(64))
    scenario_id: Mapped[str] = mapped_column(String(64))
    scenario_version: Mapped[str] = mapped_column(String(32))
    semantic_version: Mapped[str] = mapped_column(String(32))
    dataset_version: Mapped[str] = mapped_column(String(32))
    external_chat_id: Mapped[str] = mapped_column(String(128))
    generation: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ShadowEvaluation(Base):
    __tablename__ = "shadow_evaluation"
    __table_args__ = (
        Index(
            "ix_shadow_evaluation_scope_created",
            "tenant_id",
            "workspace_id",
            "scenario",
            "created_at",
        ),
    )

    shadow_evaluation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    subject_id: Mapped[str] = mapped_column(String(96), index=True)
    conversation_id: Mapped[str] = mapped_column(String(64), index=True)
    question: Mapped[str] = mapped_column(Text)
    normalized_question: Mapped[str] = mapped_column(Text)
    route_mode: Mapped[str] = mapped_column(String(32))
    scenario: Mapped[str] = mapped_column(String(64), index=True)
    scenario_version: Mapped[str] = mapped_column(String(32))
    semantic_version: Mapped[str] = mapped_column(String(32))
    dataset_version: Mapped[str] = mapped_column(String(32))
    deterministic_sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    sqlbot_sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    deterministic_result_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sqlbot_result_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    execution_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    metric_value_match: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_range_match: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dimension_match: Mapped[int | None] = mapped_column(Integer, nullable=True)
    permission_result: Mapped[str] = mapped_column(String(32))
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_usage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    trace_id: Mapped[str] = mapped_column(String(96), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class QueryRouteDecisionRecord(Base):
    __tablename__ = "query_route_decision"
    __table_args__ = (
        Index(
            "ix_query_route_decision_scope_created",
            "tenant_id",
            "workspace_id",
            "scenario",
            "created_at",
        ),
    )

    route_decision_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    subject_id: Mapped[str] = mapped_column(String(96), index=True)
    route_decision: Mapped[str] = mapped_column(String(64))
    route_reason: Mapped[str] = mapped_column(String(160))
    mode: Mapped[str] = mapped_column(String(32))
    engine: Mapped[str] = mapped_column(String(32))
    scenario: Mapped[str] = mapped_column(String(64), index=True)
    scenario_version: Mapped[str] = mapped_column(String(32))
    semantic_version: Mapped[str] = mapped_column(String(32))
    dataset_version: Mapped[str] = mapped_column(String(32))
    feature_flag_version: Mapped[str] = mapped_column(String(32))
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    trace_id: Mapped[str] = mapped_column(String(96), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


QUERY_ROUTING_TABLES = [
    SQLBotSessionBindingRecord.__table__,
    ShadowEvaluation.__table__,
    QueryRouteDecisionRecord.__table__,
]
