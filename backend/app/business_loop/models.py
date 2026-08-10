from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, event, inspect
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class AlertEvent(Base):
    __tablename__ = "p6_alert_event"
    __table_args__ = (
        UniqueConstraint("deduplication_key", name="uq_p6_alert_deduplication_key"),
        Index("ix_p6_alert_scope_status", "entity_type", "entity_id", "status"),
    )
    alert_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scenario_id: Mapped[str] = mapped_column(String(64), index=True)
    metric_id: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(32), index=True)
    entity_id: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(8), index=True)
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text)
    current_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    baseline_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    change_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    rule_id: Mapped[str] = mapped_column(String(64), index=True)
    rule_version: Mapped[str] = mapped_column(String(32))
    analysis_period_start: Mapped[date] = mapped_column(Date)
    analysis_period_end: Mapped[date] = mapped_column(Date)
    deduplication_key: Mapped[str] = mapped_column(String(64))
    analysis_run_id: Mapped[str] = mapped_column(String(64), index=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    owner_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    assignee_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sla_level: Mapped[str] = mapped_column(String(8), index=True)
    ack_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    escalation_status: Mapped[str] = mapped_column(String(32), default="NONE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    reopen_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    dataset_version: Mapped[str] = mapped_column(String(128))
    semantic_version: Mapped[str] = mapped_column(String(64))
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")


class AlertTimelineEvent(Base):
    __tablename__ = "p6_alert_timeline_event"
    __table_args__ = (Index("ix_p6_alert_timeline", "alert_id", "timestamp"),)
    timeline_event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    alert_id: Mapped[str] = mapped_column(ForeignKey("p6_alert_event.alert_id"), index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    actor: Mapped[str] = mapped_column(String(128))
    actor_type: Mapped[str] = mapped_column(String(16))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    before_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    after_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reason: Mapped[str] = mapped_column(Text)


class AlertNotificationAttempt(Base):
    __tablename__ = "p6_alert_notification_attempt"
    __table_args__ = (UniqueConstraint("alert_id", "attempt_no", name="uq_p6_alert_notification_attempt"),)
    notification_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    alert_id: Mapped[str] = mapped_column(ForeignKey("p6_alert_event.alert_id"), index=True)
    receiver: Mapped[str] = mapped_column(String(64))
    attempt_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), index=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BusinessAuditEvent(Base):
    __tablename__ = "p6_business_audit_event"
    __table_args__ = (Index("ix_p6_business_audit_resource", "resource_type", "resource_id", "timestamp"),)
    audit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    actor: Mapped[str] = mapped_column(String(128), index=True)
    actor_type: Mapped[str] = mapped_column(String(16), index=True)
    action: Mapped[str] = mapped_column(String(96), index=True)
    resource_type: Mapped[str] = mapped_column(String(64), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    before_json: Mapped[str] = mapped_column(Text, default="{}")
    after_json: Mapped[str] = mapped_column(Text, default="{}")
    reason: Mapped[str] = mapped_column(Text)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    outcome: Mapped[str] = mapped_column(String(32), index=True)


class Report(Base):
    __tablename__ = "p6_report"
    report_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    scenario_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(256))
    owner: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    current_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReportVersion(Base):
    __tablename__ = "p6_report_version"
    __table_args__ = (UniqueConstraint("report_id", "version", name="uq_p6_report_version"),)
    report_version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    report_id: Mapped[str] = mapped_column(ForeignKey("p6_report.report_id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    metric_values_json: Mapped[str] = mapped_column(Text, default="{}")
    knowledge_evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    citations_json: Mapped[str] = mapped_column(Text, default="[]")
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    dataset_version: Mapped[str] = mapped_column(String(128))
    semantic_version: Mapped[str] = mapped_column(String(64))
    analysis_run_id: Mapped[str] = mapped_column(String(64), index=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    query_plan_hash: Mapped[str] = mapped_column(String(64))
    sql_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReportEvidenceSnapshot(Base):
    __tablename__ = "p6_report_evidence_snapshot"
    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    report_id: Mapped[str] = mapped_column(ForeignKey("p6_report.report_id"), index=True)
    report_version_id: Mapped[str] = mapped_column(ForeignKey("p6_report_version.report_version_id"), unique=True)
    metric_values_json: Mapped[str] = mapped_column(Text)
    query_plan_hash: Mapped[str] = mapped_column(String(64))
    sql_hash: Mapped[str] = mapped_column(String(64))
    dataset_version: Mapped[str] = mapped_column(String(128))
    semantic_version: Mapped[str] = mapped_column(String(64))
    analysis_run_id: Mapped[str] = mapped_column(String(64), index=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    knowledge_evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    citations_json: Mapped[str] = mapped_column(Text, default="[]")
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    content_hash: Mapped[str] = mapped_column(String(64))
    snapshot_hash: Mapped[str] = mapped_column(String(64), unique=True)


class ReportReview(Base):
    __tablename__ = "p6_report_review"
    review_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    report_id: Mapped[str] = mapped_column(ForeignKey("p6_report.report_id"), index=True)
    report_version_id: Mapped[str] = mapped_column(ForeignKey("p6_report_version.report_version_id"), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    reviewer: Mapped[str] = mapped_column(String(128))
    actor_type: Mapped[str] = mapped_column(String(16))
    comment: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReportPublication(Base):
    __tablename__ = "p6_report_publication"
    publication_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    report_id: Mapped[str] = mapped_column(ForeignKey("p6_report.report_id"), index=True)
    report_version_id: Mapped[str] = mapped_column(ForeignKey("p6_report_version.report_version_id"), unique=True)
    evidence_snapshot_id: Mapped[str] = mapped_column(ForeignKey("p6_report_evidence_snapshot.snapshot_id"), unique=True)
    published_by: Mapped[str] = mapped_column(String(128))
    actor_type: Mapped[str] = mapped_column(String(16))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(32), default="PUBLISHED")


class MetricGovernanceVersion(Base):
    __tablename__ = "p6_metric_governance_version"
    __table_args__ = (
        UniqueConstraint("metric_id", "version", name="uq_p6_metric_governance_version"),
        Index("ix_p6_metric_governance_status", "metric_id", "status"),
    )
    metric_version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    metric_id: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(128))
    business_definition: Mapped[str] = mapped_column(Text)
    formula: Mapped[str] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(String(32))
    dimensions_json: Mapped[str] = mapped_column(Text)
    time_grain: Mapped[str] = mapped_column(String(32))
    source_tables_json: Mapped[str] = mapped_column(Text)
    owner: Mapped[str] = mapped_column(String(128))
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    change_reason: Mapped[str] = mapped_column(Text)
    impact_analysis_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(32), index=True)
    review_outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_by: Mapped[str] = mapped_column(String(128))
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def _published_version_is_immutable(_mapper, _connection, target: ReportVersion) -> None:
    history = inspect(target).attrs.status.history
    previous = history.deleted[0] if history.deleted else target.status
    if previous == "PUBLISHED":
        raise ValueError("published report versions are immutable")


def _immutable_snapshot(_mapper, _connection, _target: ReportEvidenceSnapshot) -> None:
    raise ValueError("report evidence snapshots are immutable")


event.listen(ReportVersion, "before_update", _published_version_is_immutable)
event.listen(ReportVersion, "before_delete", _published_version_is_immutable)
event.listen(ReportEvidenceSnapshot, "before_update", _immutable_snapshot)
event.listen(ReportEvidenceSnapshot, "before_delete", _immutable_snapshot)


P6_TABLES = (
    AlertEvent.__table__, AlertTimelineEvent.__table__, AlertNotificationAttempt.__table__,
    BusinessAuditEvent.__table__, Report.__table__, ReportVersion.__table__,
    ReportEvidenceSnapshot.__table__, ReportReview.__table__, ReportPublication.__table__,
    MetricGovernanceVersion.__table__,
)
