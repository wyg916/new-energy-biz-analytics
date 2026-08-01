from __future__ import annotations

import csv
import io
import json
import re
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.governance.models import GovernanceAuditEvent, SecurityAlert
from app.platform.identity import IdentityContext


SENSITIVE_KEY = re.compile(r"(?i)(secret|password|token|api[_-]?key|credential_value|connection_string)")


def _safe_detail(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if SENSITIVE_KEY.search(str(key)) else _safe_detail(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_safe_detail(item) for item in value]
    if isinstance(value, str) and len(value) > 1000:
        return value[:1000]
    return value


class SecurityAlertEngine:
    RULES = {
        "authorization.denied": ("CONSECUTIVE_AUTH_DENIAL", "medium", 3),
        "authorization.cross_tenant": ("CROSS_TENANT_ATTEMPT", "high", 1),
        "credential.use_failed": ("CREDENTIAL_REFERENCE_FAILURE", "high", 1),
        "sql.guard_violation": ("SQL_SAFETY_VIOLATION", "high", 1),
        "procedure.activate_denied": ("UNREVIEWED_PROCEDURE_ACTIVATION", "high", 1),
        "legal_hold.delete_blocked": ("LEGAL_HOLD_DELETE_BLOCKED", "medium", 1),
    }

    @classmethod
    def observe(cls, db: Session, event: GovernanceAuditEvent) -> SecurityAlert | None:
        rule = cls.RULES.get(event.action)
        if rule is None:
            return None
        rule_code, severity, threshold = rule
        correlation_key = f"{event.actor_subject_id}:{event.resource_type}:{event.resource_id or '*'}"
        alert = db.scalar(select(SecurityAlert).where(
            SecurityAlert.tenant_id == event.tenant_id,
            SecurityAlert.workspace_id == event.workspace_id,
            SecurityAlert.rule_code == rule_code,
            SecurityAlert.correlation_key == correlation_key,
            SecurityAlert.status.in_(("OBSERVING", "OPEN")),
        ))
        if alert is None:
            alert = SecurityAlert(
                alert_id=f"ALERT-{uuid4()}",
                tenant_id=event.tenant_id,
                workspace_id=event.workspace_id,
                rule_code=rule_code,
                correlation_key=correlation_key,
                severity=severity,
                status="OPEN" if threshold == 1 else "OBSERVING",
                event_count=1,
                summary=f"治理规则 {rule_code} 已触发",
                trace_id=event.trace_id,
            )
            db.add(alert)
        else:
            alert.event_count += 1
            alert.last_seen_at = datetime.now(UTC)
            alert.trace_id = event.trace_id
        if alert.event_count < threshold:
            return None
        alert.status = "OPEN"
        return alert


def record_governance_event(
    db: Session,
    identity: IdentityContext,
    *,
    action: str,
    resource_type: str,
    resource_id: str | None,
    result: str,
    trace_id: str | None = None,
    detail: dict | None = None,
    commit: bool = False,
) -> GovernanceAuditEvent:
    event = GovernanceAuditEvent(
        event_id=f"GOVAUD-{uuid4()}",
        tenant_id=identity.tenant_id,
        workspace_id=identity.workspace_id,
        actor_subject_id=identity.subject_id,
        principal_id=identity.principal_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        result=result,
        trace_id=trace_id or identity.request_id,
        detail_json=json.dumps(_safe_detail(detail or {}), ensure_ascii=False, sort_keys=True),
    )
    db.add(event)
    db.flush()
    SecurityAlertEngine.observe(db, event)
    if commit:
        db.commit()
    return event


class GovernanceAuditQuery:
    def __init__(self, db: Session, identity: IdentityContext) -> None:
        self.db = db
        self.identity = identity

    def search(
        self,
        *,
        actor: str | None = None,
        resource: str | None = None,
        action: str | None = None,
        result: str | None = None,
        trace_id: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[GovernanceAuditEvent], int]:
        filters = [
            GovernanceAuditEvent.tenant_id == self.identity.tenant_id,
            GovernanceAuditEvent.workspace_id == self.identity.workspace_id,
        ]
        if actor:
            filters.append(GovernanceAuditEvent.actor_subject_id == actor)
        if resource:
            filters.append(GovernanceAuditEvent.resource_type == resource)
        if action:
            filters.append(GovernanceAuditEvent.action == action)
        if result:
            filters.append(GovernanceAuditEvent.result == result)
        if trace_id:
            filters.append(GovernanceAuditEvent.trace_id == trace_id)
        if start:
            filters.append(GovernanceAuditEvent.created_at >= start)
        if end:
            filters.append(GovernanceAuditEvent.created_at < end)
        safe_size = min(max(page_size, 1), 200)
        safe_page = max(page, 1)
        total = int(self.db.scalar(select(func.count()).select_from(GovernanceAuditEvent).where(*filters)) or 0)
        rows = list(self.db.scalars(select(GovernanceAuditEvent).where(*filters).order_by(
            desc(GovernanceAuditEvent.created_at), GovernanceAuditEvent.event_id,
        ).offset((safe_page - 1) * safe_size).limit(safe_size)).all())
        return rows, total

    def export_csv(self, **filters) -> str:
        rows, _ = self.search(page=1, page_size=200, **filters)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(("event_id", "tenant_id", "actor", "resource_type", "resource_id", "action", "result", "trace_id", "created_at"))
        for row in rows:
            writer.writerow((row.event_id, row.tenant_id, row.actor_subject_id, row.resource_type, row.resource_id, row.action, row.result, row.trace_id, row.created_at.isoformat()))
        return output.getvalue()
