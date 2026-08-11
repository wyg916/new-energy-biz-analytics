from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.dependencies import current_user
from app.core.database import get_db
from app.models.auth import User
from app.business_loop.models import BusinessAuditEvent


class BusinessLoopError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


ROLE_CAPABILITIES = {
    "executive": {"view"},
    "viewer": {"view"},
    "regional_manager": {"view", "alert.handle", "report.author"},
    "analyst": {"view", "alert.handle", "report.author"},
    "analyst_admin": {
        "view", "alert.handle", "alert.admin", "report.author", "report.review",
        "report.publish", "metric.govern", "audit.view",
    },
}

SENSITIVE_PARTS = ("password", "secret", "token", "credential", "authorization")


def _json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def sanitized(value):
    if isinstance(value, dict):
        return {
            str(key): ("[REDACTED]" if any(part in str(key).lower() for part in SENSITIVE_PARTS) else sanitized(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitized(item) for item in value]
    return value


def json_text(value) -> str:
    return json.dumps(sanitized(value), ensure_ascii=False, sort_keys=True, default=_json_default)


def request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or f"REQ-{uuid4()}"


def record_audit(
    db: Session,
    *,
    actor: str,
    actor_type: str,
    action: str,
    resource_type: str,
    resource_id: str | None,
    before: dict | None,
    after: dict | None,
    reason: str,
    request_id_value: str,
    run_id: str,
    outcome: str = "SUCCESS",
) -> BusinessAuditEvent:
    event = BusinessAuditEvent(
        audit_id=f"P6-AUD-{uuid4()}", actor=actor, actor_type=actor_type,
        action=action, resource_type=resource_type, resource_id=resource_id,
        before_json=json_text(before or {}), after_json=json_text(after or {}), reason=reason,
        request_id=request_id_value, run_id=run_id, outcome=outcome,
    )
    db.add(event)
    return event


def actor_type_for(name: str) -> str:
    return "SYSTEM" if name in {"system_reviewer", "system_approver", "quality_agent"} else "HUMAN"


def require_capability(capability: str):
    def dependency(
        request: Request,
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if capability not in ROLE_CAPABILITIES.get(user.role, set()):
            run_id = f"P6-DENIED-{uuid4()}"
            record_audit(
                db, actor=user.username, actor_type="HUMAN", action=f"rbac.{capability}.denied",
                resource_type="p6_capability", resource_id=capability, before={}, after={},
                reason="RBAC permission denied", request_id_value=request_id(request),
                run_id=run_id, outcome="DENIED",
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "P6_RBAC_DENIED", "message": "当前角色无权执行该操作"},
            )
        return user
    return dependency


def as_http_error(exc: BusinessLoopError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)})
