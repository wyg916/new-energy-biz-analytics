from __future__ import annotations

import json
from datetime import date
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.dependencies import current_user
from app.business_loop.alerts import ALERT_STATES, SLA_POLICY, AlertService
from app.business_loop.common import BusinessLoopError, as_http_error, request_id, require_capability
from app.business_loop.metrics import MetricGovernanceService
from app.business_loop.models import BusinessAuditEvent
from app.business_loop.reports import GovernedReportService
from app.core.database import get_db
from app.models.auth import User


router = APIRouter(tags=["p6-business-loop"])


def _run(callback: Callable[[], Any]):
    try:
        return callback()
    except BusinessLoopError as exc:
        raise as_http_error(exc) from exc


class ReasonRequest(BaseModel):
    reason: str = Field(min_length=2, max_length=2000)


class AlertGenerateRequest(BaseModel):
    metric_id: str = Field(min_length=2, max_length=64)
    start: date
    end_exclusive: date
    threshold: float = Field(default=.05, ge=.0001, le=1)
    scenario_id: str = Field(default="charging_ops", min_length=2, max_length=64)


class AlertActionRequest(ReasonRequest):
    assignee_id: str | None = Field(default=None, max_length=64)
    summary: str | None = Field(default=None, max_length=4000)


class ReportCreateRequest(BaseModel):
    report_type: str = Field(default="monthly", pattern="^(weekly|monthly)$")
    start: date
    end_exclusive: date
    title: str | None = Field(default=None, max_length=256)
    knowledge_evidence: list[dict] = Field(default_factory=list)
    citations: list[dict] = Field(default_factory=list)


class ReportVersionRequest(ReasonRequest):
    content: str | None = Field(default=None, min_length=10)
    summary: str | None = Field(default=None, max_length=4000)


class ReviewRequest(BaseModel):
    reviewer: str | None = Field(default=None, max_length=128)
    actor_type: str = Field(default="HUMAN", pattern="^(HUMAN|SYSTEM)$")
    comment: str = Field(min_length=2, max_length=4000)


class PublishRequest(ReasonRequest):
    publisher: str | None = Field(default=None, max_length=128)
    actor_type: str = Field(default="HUMAN", pattern="^(HUMAN|SYSTEM)$")


class MetricDraftRequest(BaseModel):
    metric_id: str = Field(min_length=2, max_length=64)
    version: str | None = Field(default=None, max_length=32)
    name: str | None = Field(default=None, max_length=128)
    business_definition: str | None = None
    formula: str | None = None
    unit: str | None = Field(default=None, max_length=32)
    dimensions: list[str] | None = None
    time_grain: str | None = Field(default=None, max_length=32)
    source_tables: list[str] | None = None
    owner: str | None = Field(default=None, max_length=128)
    effective_from: date | None = None
    change_reason: str = Field(min_length=2, max_length=4000)


class MetricUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    business_definition: str | None = None
    formula: str | None = None
    unit: str | None = Field(default=None, max_length=32)
    dimensions: list[str] | None = None
    time_grain: str | None = Field(default=None, max_length=32)
    source_tables: list[str] | None = None
    owner: str | None = Field(default=None, max_length=128)
    effective_from: date | None = None
    change_reason: str | None = Field(default=None, max_length=4000)
    reason: str = Field(min_length=2, max_length=2000)


@router.get("/alerts")
def list_alerts(
    request: Request, status: str | None = Query(default=None), severity: str | None = Query(default=None),
    db: Session = Depends(get_db), user: User = Depends(require_capability("view")),
) -> dict:
    if status and status not in ALERT_STATES:
        raise HTTPException(status_code=422, detail={"code": "ALERT_STATUS_INVALID", "message": "预警状态不合法"})
    if severity and severity not in SLA_POLICY:
        raise HTTPException(status_code=422, detail={"code": "ALERT_SEVERITY_INVALID", "message": "预警等级不合法"})
    return {"rows": AlertService(db, user, request_id=request_id(request)).list(status=status, severity=severity), "sla_policy": SLA_POLICY}


@router.post("/alerts/generate")
def generate_alert(payload: AlertGenerateRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_capability("alert.admin"))) -> dict:
    if payload.start >= payload.end_exclusive:
        raise HTTPException(status_code=422, detail={"code": "INVALID_RANGE", "message": "时间范围不合法"})
    return _run(lambda: AlertService(db, user, request_id=request_id(request)).generate(**payload.model_dump()))


@router.get("/alerts/{alert_id}")
def alert_detail(alert_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_capability("view"))) -> dict:
    return _run(lambda: AlertService(db, user, request_id=request_id(request)).detail(alert_id))


@router.get("/alerts/{alert_id}/timeline")
def alert_timeline(alert_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_capability("view"))) -> dict:
    return {"rows": _run(lambda: AlertService(db, user, request_id=request_id(request)).timeline(alert_id))}


@router.post("/alerts/{alert_id}/comments")
def comment_alert(alert_id: str, payload: ReasonRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_capability("alert.handle"))) -> dict:
    return _run(lambda: AlertService(db, user, request_id=request_id(request)).comment(alert_id, reason=payload.reason))


def _alert_transition(alert_id: str, action: str, payload: AlertActionRequest, request: Request, db: Session, user: User) -> dict:
    return _run(lambda: AlertService(db, user, request_id=request_id(request)).transition(
        alert_id, action, reason=payload.reason, assignee_id=payload.assignee_id, summary=payload.summary,
    ))


@router.post("/alerts/{alert_id}/assign")
def assign_alert(alert_id: str, payload: AlertActionRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_capability("alert.admin"))) -> dict:
    return _alert_transition(alert_id, "assign", payload, request, db, user)


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: str, payload: AlertActionRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_capability("alert.handle"))) -> dict:
    return _alert_transition(alert_id, "acknowledge", payload, request, db, user)


@router.post("/alerts/{alert_id}/in-progress")
def start_alert(alert_id: str, payload: AlertActionRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_capability("alert.handle"))) -> dict:
    return _alert_transition(alert_id, "in_progress", payload, request, db, user)


@router.post("/alerts/{alert_id}/resolve")
def resolve_alert(alert_id: str, payload: AlertActionRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_capability("alert.handle"))) -> dict:
    return _alert_transition(alert_id, "resolve", payload, request, db, user)


@router.post("/alerts/{alert_id}/verify")
def verify_alert(alert_id: str, payload: AlertActionRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_capability("alert.admin"))) -> dict:
    return _alert_transition(alert_id, "verify", payload, request, db, user)


@router.post("/alerts/{alert_id}/close")
def close_alert(alert_id: str, payload: AlertActionRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_capability("alert.admin"))) -> dict:
    return _alert_transition(alert_id, "close", payload, request, db, user)


@router.post("/alerts/{alert_id}/reopen")
def reopen_alert(alert_id: str, payload: AlertActionRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_capability("alert.admin"))) -> dict:
    return _alert_transition(alert_id, "reopen", payload, request, db, user)


@router.get("/reports")
def list_reports(request: Request, db: Session = Depends(get_db), user: User = Depends(require_capability("view"))) -> dict:
    return {"rows": GovernedReportService(db, user, request_id=request_id(request)).list()}


@router.post("/reports")
def create_report(payload: ReportCreateRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_capability("report.author"))) -> dict:
    if payload.start >= payload.end_exclusive:
        raise HTTPException(status_code=422, detail={"code": "INVALID_RANGE", "message": "时间范围不合法"})
    return _run(lambda: GovernedReportService(db, user, request_id=request_id(request)).create(**payload.model_dump()))


@router.get("/reports/{report_id}")
def report_detail(report_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_capability("view"))) -> dict:
    return _run(lambda: GovernedReportService(db, user, request_id=request_id(request)).detail(report_id))


@router.post("/reports/{report_id}/versions")
def new_report_version(report_id: str, payload: ReportVersionRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_capability("report.author"))) -> dict:
    return _run(lambda: GovernedReportService(db, user, request_id=request_id(request)).new_version(report_id, **payload.model_dump()))


def _report_review(report_id: str, action: str, payload: ReviewRequest, request: Request, db: Session, user: User) -> dict:
    reviewer = payload.reviewer or user.username
    return _run(lambda: GovernedReportService(db, user, request_id=request_id(request)).review(
        report_id, action=action, reviewer=reviewer, actor_type=payload.actor_type, comment=payload.comment,
    ))


@router.post("/reports/{report_id}/submit-review")
def submit_report_review(report_id: str, payload: ReviewRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_capability("report.author"))) -> dict:
    return _report_review(report_id, "submit", payload, request, db, user)


@router.post("/reports/{report_id}/approve")
def approve_report(report_id: str, payload: ReviewRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_capability("report.review"))) -> dict:
    return _report_review(report_id, "approve", payload, request, db, user)


@router.post("/reports/{report_id}/reject")
def reject_report(report_id: str, payload: ReviewRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_capability("report.review"))) -> dict:
    return _report_review(report_id, "reject", payload, request, db, user)


@router.post("/reports/{report_id}/publish")
def publish_report(report_id: str, payload: PublishRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_capability("report.publish"))) -> dict:
    return _run(lambda: GovernedReportService(db, user, request_id=request_id(request)).publish(
        report_id, publisher=payload.publisher or user.username, actor_type=payload.actor_type, reason=payload.reason,
    ))


@router.post("/reports/{report_id}/archive")
def archive_report(report_id: str, payload: ReasonRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_capability("report.publish"))) -> dict:
    return _run(lambda: GovernedReportService(db, user, request_id=request_id(request)).archive(report_id, reason=payload.reason))


@router.get("/reports/{report_id}/evidence")
def report_evidence(report_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_capability("view"))) -> dict:
    return _run(lambda: GovernedReportService(db, user, request_id=request_id(request)).evidence(report_id))


@router.get("/metrics/governance")
def list_metric_governance(request: Request, db: Session = Depends(get_db), user: User = Depends(require_capability("view"))) -> dict:
    return {"rows": MetricGovernanceService(db, user, request_id=request_id(request)).list()}


@router.get("/metrics/governance/{metric_id}")
def metric_governance_detail(metric_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_capability("view"))) -> dict:
    return _run(lambda: MetricGovernanceService(db, user, request_id=request_id(request)).detail(metric_id))


@router.post("/metrics/governance/drafts")
def create_metric_draft(payload: MetricDraftRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_capability("metric.govern"))) -> dict:
    return _run(lambda: MetricGovernanceService(db, user, request_id=request_id(request)).create_draft(
        payload.model_dump(exclude_none=True)
    ))


@router.patch("/metrics/governance/versions/{version_id}")
def update_metric_draft(version_id: str, payload: MetricUpdateRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_capability("metric.govern"))) -> dict:
    values = payload.model_dump(exclude_none=True)
    reason = values.pop("reason")
    return _run(lambda: MetricGovernanceService(db, user, request_id=request_id(request)).update_draft(version_id, values, reason=reason))


@router.post("/metrics/governance/versions/{version_id}/impact-analysis")
def analyze_metric_impact(version_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(require_capability("metric.govern"))) -> dict:
    return _run(lambda: MetricGovernanceService(db, user, request_id=request_id(request)).impact_analysis(version_id))


def _metric_review(version_id: str, action: str, payload: ReasonRequest, request: Request, db: Session, user: User) -> dict:
    return _run(lambda: MetricGovernanceService(db, user, request_id=request_id(request)).review(version_id, action=action, reason=payload.reason))


@router.post("/metrics/governance/versions/{version_id}/submit-review")
def submit_metric_review(version_id: str, payload: ReasonRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_capability("metric.govern"))) -> dict:
    return _metric_review(version_id, "submit", payload, request, db, user)


@router.post("/metrics/governance/versions/{version_id}/approve")
def approve_metric(version_id: str, payload: ReasonRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_capability("metric.govern"))) -> dict:
    return _metric_review(version_id, "approve", payload, request, db, user)


@router.post("/metrics/governance/versions/{version_id}/reject")
def reject_metric(version_id: str, payload: ReasonRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_capability("metric.govern"))) -> dict:
    return _metric_review(version_id, "reject", payload, request, db, user)


@router.post("/metrics/governance/versions/{version_id}/publish")
def publish_metric(version_id: str, payload: ReasonRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_capability("metric.govern"))) -> dict:
    return _run(lambda: MetricGovernanceService(db, user, request_id=request_id(request)).publish(version_id, reason=payload.reason))


@router.post("/metrics/governance/versions/{version_id}/deprecate")
def deprecate_metric(version_id: str, payload: ReasonRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_capability("metric.govern"))) -> dict:
    return _run(lambda: MetricGovernanceService(db, user, request_id=request_id(request)).deprecate(version_id, reason=payload.reason))


@router.get("/business-audit")
def list_business_audit(
    limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db),
    _user: User = Depends(require_capability("audit.view")),
) -> dict:
    rows = db.scalars(select(BusinessAuditEvent).order_by(desc(BusinessAuditEvent.timestamp)).limit(limit)).all()
    return {"rows": [{
        "audit_id": row.audit_id, "actor": row.actor, "actor_type": row.actor_type,
        "action": row.action, "resource_type": row.resource_type, "resource_id": row.resource_id,
        "before": json.loads(row.before_json), "after": json.loads(row.after_json), "reason": row.reason,
        "request_id": row.request_id, "run_id": row.run_id, "timestamp": row.timestamp.isoformat(),
        "outcome": row.outcome,
    } for row in rows]}
