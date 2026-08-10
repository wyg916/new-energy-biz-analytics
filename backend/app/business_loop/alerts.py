from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.business_loop.common import BusinessLoopError, actor_type_for, record_audit
from app.business_loop.models import AlertEvent, AlertNotificationAttempt, AlertTimelineEvent
from app.models.auth import User
from app.models.business import Station
from app.services.diagnostics import DiagnosticService


ALERT_STATES = {"OPEN", "ASSIGNED", "ACKNOWLEDGED", "IN_PROGRESS", "RESOLVED", "VERIFIED", "CLOSED", "REOPENED"}
SLA_POLICY = {
    "P0": {"ack_hours": 1, "resolve_hours": 4},
    "P1": {"ack_hours": 4, "resolve_hours": 24},
    "P2": {"ack_hours": 8, "resolve_hours": 72},
    "P3": {"ack_hours": 24, "resolve_hours": 168},
}
TRANSITIONS = {
    "assign": ({"OPEN", "REOPENED", "ASSIGNED"}, "ASSIGNED"),
    "acknowledge": ({"OPEN", "ASSIGNED", "REOPENED"}, "ACKNOWLEDGED"),
    "in_progress": ({"ACKNOWLEDGED"}, "IN_PROGRESS"),
    "resolve": ({"ACKNOWLEDGED", "IN_PROGRESS"}, "RESOLVED"),
    "verify": ({"RESOLVED"}, "VERIFIED"),
    "close": ({"VERIFIED"}, "CLOSED"),
    "reopen": ({"RESOLVED", "VERIFIED", "CLOSED"}, "REOPENED"),
}


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _severity(rate: float) -> str:
    absolute = abs(rate)
    if absolute >= .5:
        return "P0"
    if absolute >= .25:
        return "P1"
    if absolute >= .1:
        return "P2"
    return "P3"


def alert_state(alert: AlertEvent) -> dict:
    now = datetime.now(UTC)
    ack_overdue = alert.acknowledged_at is None and _aware(alert.ack_due_at) < now
    resolve_overdue = alert.resolved_at is None and _aware(alert.due_at) < now
    escalation = "RESOLVE_OVERDUE" if resolve_overdue else "ACK_OVERDUE" if ack_overdue else alert.escalation_status
    return {
        "alert_id": alert.alert_id, "scenario_id": alert.scenario_id, "metric_id": alert.metric_id,
        "entity_type": alert.entity_type, "entity_id": alert.entity_id, "severity": alert.severity,
        "title": alert.title, "description": alert.description,
        "current_value": float(alert.current_value) if alert.current_value is not None else None,
        "baseline_value": float(alert.baseline_value) if alert.baseline_value is not None else None,
        "change_rate": float(alert.change_rate) if alert.change_rate is not None else None,
        "rule_id": alert.rule_id, "rule_version": alert.rule_version,
        "analysis_period": [alert.analysis_period_start.isoformat(), alert.analysis_period_end.isoformat()],
        "analysis_run_id": alert.analysis_run_id, "run_id": alert.run_id, "status": alert.status,
        "owner_id": alert.owner_id, "assignee_id": alert.assignee_id, "sla_level": alert.sla_level,
        "sla": SLA_POLICY[alert.sla_level], "ack_due_at": alert.ack_due_at.isoformat(),
        "due_at": alert.due_at.isoformat(), "overdue": ack_overdue or resolve_overdue,
        "escalation_status": escalation, "created_at": alert.created_at.isoformat(),
        "assigned_at": alert.assigned_at.isoformat() if alert.assigned_at else None,
        "acknowledged_at": alert.acknowledged_at.isoformat() if alert.acknowledged_at else None,
        "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None,
        "verified_at": alert.verified_at.isoformat() if alert.verified_at else None,
        "closed_at": alert.closed_at.isoformat() if alert.closed_at else None,
        "resolution_summary": alert.resolution_summary, "verification_summary": alert.verification_summary,
        "reopen_reason": alert.reopen_reason, "dataset_version": alert.dataset_version,
        "semantic_version": alert.semantic_version, "evidence": json.loads(alert.evidence_json),
    }


class ControlledAlertReceiver:
    """Local acceptance receiver. It is not an enterprise notification integration."""

    def __init__(self, outcomes: list[str] | None = None):
        self.outcomes = outcomes or ["ACKNOWLEDGED"]

    def deliver(self, attempt_no: int, _alert: AlertEvent) -> tuple[str, str | None]:
        outcome = self.outcomes[min(attempt_no - 1, len(self.outcomes) - 1)]
        return (outcome, None if outcome == "ACKNOWLEDGED" else "CONTROLLED_RECEIVER_FAILURE")


class AlertService:
    def __init__(self, db: Session, user: User, *, request_id: str, receiver: ControlledAlertReceiver | None = None):
        self.db = db
        self.user = user
        self.request_id = request_id
        self.receiver = receiver or ControlledAlertReceiver()

    def _scope_filters(self):
        if not self.user.region_code:
            return []
        station_ids = select(Station.station_id).where(Station.region_id == self.user.region_code)
        return [
            (AlertEvent.entity_type == "REGION") & (AlertEvent.entity_id == self.user.region_code)
            | (AlertEvent.entity_type == "STATION") & (AlertEvent.entity_id.in_(station_ids))
        ]

    def list(self, *, status: str | None = None, severity: str | None = None) -> list[dict]:
        filters = self._scope_filters()
        if status:
            filters.append(AlertEvent.status == status)
        if severity:
            filters.append(AlertEvent.severity == severity)
        rows = self.db.scalars(select(AlertEvent).where(*filters).order_by(AlertEvent.created_at.desc())).all()
        return [alert_state(row) for row in rows]

    def get(self, alert_id: str) -> AlertEvent:
        row = self.db.scalar(select(AlertEvent).where(AlertEvent.alert_id == alert_id, *self._scope_filters()))
        if row is None:
            raise BusinessLoopError("ALERT_NOT_FOUND", "预警不存在或不在授权范围内", 404)
        return row

    def detail(self, alert_id: str) -> dict:
        row = self.get(alert_id)
        result = alert_state(row)
        attempts = self.db.scalars(select(AlertNotificationAttempt).where(
            AlertNotificationAttempt.alert_id == alert_id
        ).order_by(AlertNotificationAttempt.attempt_no)).all()
        result["notification_attempts"] = [{
            "attempt_no": item.attempt_no, "receiver": item.receiver, "status": item.status,
            "failure_code": item.failure_code, "requested_at": item.requested_at.isoformat(),
            "acknowledged_at": item.acknowledged_at.isoformat() if item.acknowledged_at else None,
        } for item in attempts]
        return result

    def generate(self, *, metric_id: str, start: date, end_exclusive: date, threshold: float, scenario_id: str = "charging_ops") -> dict:
        diagnostic = DiagnosticService(self.db, self.user).anomalies(metric_id, start, end_exclusive, threshold)
        if not diagnostic["triggered"]:
            return {"created": False, "deduplicated": False, "diagnostic": diagnostic, "alert": None}
        entity_type = "REGION" if self.user.region_code else "PORTFOLIO"
        entity_id = self.user.region_code or "ALL"
        rule_id = f"{metric_id}.mom_change"
        dedup_source = "|".join((scenario_id, metric_id, entity_type, entity_id, rule_id, start.isoformat(), end_exclusive.isoformat()))
        dedup_key = hashlib.sha256(dedup_source.encode()).hexdigest()
        existing = self.db.scalar(select(AlertEvent).where(AlertEvent.deduplication_key == dedup_key))
        if existing:
            record_audit(
                self.db, actor=self.user.username, actor_type="HUMAN", action="alert.generate_deduplicated",
                resource_type="alert", resource_id=existing.alert_id, before=alert_state(existing), after=alert_state(existing),
                reason="diagnostic deduplication key matched", request_id_value=self.request_id,
                run_id=diagnostic["metadata"]["analysis_run_id"],
            )
            self.db.commit()
            return {"created": False, "deduplicated": True, "diagnostic": diagnostic, "alert": alert_state(existing)}
        rate = float(diagnostic["change_rate"])
        level = _severity(rate)
        policy = SLA_POLICY[level]
        now = datetime.now(UTC)
        metadata = diagnostic["metadata"]
        alert = AlertEvent(
            alert_id=f"ALT-{uuid4()}", scenario_id=scenario_id, metric_id=metric_id,
            entity_type=entity_type, entity_id=entity_id, severity=level,
            title=f"{metric_id} 环比变化预警", description="后端治理规则检测到指标环比变化超过受控阈值。",
            current_value=Decimal(str(diagnostic["current"])), baseline_value=Decimal(str(diagnostic["previous"])),
            change_rate=Decimal(str(rate)), rule_id=rule_id, rule_version="1.0.0",
            analysis_period_start=start, analysis_period_end=end_exclusive, deduplication_key=dedup_key,
            analysis_run_id=metadata["analysis_run_id"], run_id=metadata["analysis_run_id"], status="OPEN",
            owner_id=self.user.username, assignee_id=None, sla_level=level,
            ack_due_at=now + timedelta(hours=policy["ack_hours"]), due_at=now + timedelta(hours=policy["resolve_hours"]),
            escalation_status="NONE", created_at=now,
            dataset_version=metadata.get("dataset_version") or metadata.get("source_dataset_version") or "unknown",
            semantic_version=metadata.get("semantic_version") or "0.1.0",
            evidence_json=json.dumps({"diagnostic": diagnostic, "knowledge_evidence": [], "citations": []}, ensure_ascii=False, default=str),
        )
        self.db.add(alert)
        self._timeline(alert, "created", None, "OPEN", "diagnostic rule triggered")
        self.db.flush()
        self._deliver(alert)
        record_audit(
            self.db, actor=self.user.username, actor_type="HUMAN", action="alert.created",
            resource_type="alert", resource_id=alert.alert_id, before={}, after=alert_state(alert),
            reason="diagnostic rule triggered", request_id_value=self.request_id, run_id=alert.run_id,
        )
        self.db.commit()
        return {"created": True, "deduplicated": False, "diagnostic": diagnostic, "alert": alert_state(alert)}

    def _deliver(self, alert: AlertEvent) -> None:
        for attempt_no in (1, 2):
            status, failure = self.receiver.deliver(attempt_no, alert)
            item = AlertNotificationAttempt(
                notification_id=f"NTF-{uuid4()}", alert_id=alert.alert_id,
                receiver="controlled-alert-receiver", attempt_no=attempt_no, status=status,
                failure_code=failure, acknowledged_at=datetime.now(UTC) if status == "ACKNOWLEDGED" else None,
            )
            self.db.add(item)
            record_audit(
                self.db, actor="quality_agent", actor_type="SYSTEM", action="alert.notification_delivery",
                resource_type="alert_notification", resource_id=item.notification_id, before={},
                after={"attempt_no": attempt_no, "status": status, "failure_code": failure},
                reason="controlled receiver delivery attempt", request_id_value=self.request_id,
                run_id=alert.run_id, outcome="SUCCESS" if status == "ACKNOWLEDGED" else "FAILED",
            )
            if status == "ACKNOWLEDGED":
                break

    def _timeline(self, alert: AlertEvent, event_type: str, before: str | None, after: str | None, reason: str, actor: str | None = None) -> None:
        actor_name = actor or self.user.username
        self.db.add(AlertTimelineEvent(
            timeline_event_id=f"ATL-{uuid4()}", alert_id=alert.alert_id, event_type=event_type,
            actor=actor_name, actor_type=actor_type_for(actor_name), before_state=before, after_state=after,
            reason=reason,
        ))

    def timeline(self, alert_id: str) -> list[dict]:
        self.get(alert_id)
        rows = self.db.scalars(select(AlertTimelineEvent).where(
            AlertTimelineEvent.alert_id == alert_id
        ).order_by(AlertTimelineEvent.timestamp, AlertTimelineEvent.timeline_event_id)).all()
        return [{
            "timeline_event_id": row.timeline_event_id, "event_type": row.event_type,
            "actor": row.actor, "actor_type": row.actor_type, "timestamp": row.timestamp.isoformat(),
            "before_state": row.before_state, "after_state": row.after_state, "reason": row.reason,
        } for row in rows]

    def comment(self, alert_id: str, *, reason: str) -> dict:
        alert = self.get(alert_id)
        self._timeline(alert, "commented", alert.status, alert.status, reason)
        record_audit(
            self.db, actor=self.user.username, actor_type="HUMAN", action="alert.commented",
            resource_type="alert", resource_id=alert.alert_id, before={"status": alert.status},
            after={"status": alert.status, "comment_recorded": True}, reason=reason,
            request_id_value=self.request_id, run_id=alert.run_id,
        )
        self.db.commit()
        return alert_state(alert)

    def transition(self, alert_id: str, action: str, *, reason: str, assignee_id: str | None = None, summary: str | None = None) -> dict:
        if action not in TRANSITIONS:
            raise BusinessLoopError("ALERT_ACTION_INVALID", "不支持的预警动作", 422)
        alert = self.get(alert_id)
        allowed, target = TRANSITIONS[action]
        if alert.status not in allowed:
            raise BusinessLoopError("ALERT_STATE_CONFLICT", f"{alert.status} 状态不能执行 {action}")
        before_view = alert_state(alert)
        before = alert.status
        now = datetime.now(UTC)
        if action == "assign":
            if not assignee_id:
                raise BusinessLoopError("ASSIGNEE_REQUIRED", "分派必须指定处理人", 422)
            alert.assignee_id = assignee_id
            alert.assigned_at = now
        elif action == "acknowledge":
            alert.acknowledged_at = now
        elif action == "resolve":
            if not summary:
                raise BusinessLoopError("RESOLUTION_REQUIRED", "解决预警必须填写处置摘要", 422)
            alert.resolution_summary = summary
            alert.resolved_at = now
        elif action == "verify":
            if not summary:
                raise BusinessLoopError("VERIFICATION_REQUIRED", "验证预警必须填写验证摘要", 422)
            alert.verification_summary = summary
            alert.verified_at = now
        elif action == "close":
            alert.closed_at = now
        elif action == "reopen":
            alert.reopen_reason = reason
            alert.closed_at = None
            alert.verified_at = None
            alert.resolved_at = None
        alert.status = target
        self._timeline(alert, "status_changed" if action == "in_progress" else action, before, target, reason)
        after_view = alert_state(alert)
        record_audit(
            self.db, actor=self.user.username, actor_type="HUMAN", action=f"alert.{action}",
            resource_type="alert", resource_id=alert.alert_id, before=before_view, after=after_view,
            reason=reason, request_id_value=self.request_id, run_id=alert.run_id,
        )
        self.db.commit()
        return after_view
