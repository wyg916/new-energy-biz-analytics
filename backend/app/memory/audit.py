from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy.orm import Session

from app.memory.models import MemoryAuditEvent
from app.platform.identity import IdentityContext


def audit_memory_use(
    db: Session,
    identity: IdentityContext,
    *,
    action: str,
    outcome: str,
    memory_id: str | None = None,
    candidate_id: str | None = None,
    run_id: str | None = None,
    trace_id: str | None = None,
    reason: str | None = None,
    detail: dict | None = None,
    commit: bool = False,
) -> MemoryAuditEvent:
    event = MemoryAuditEvent(
        audit_id=f"MEMAUD-{uuid4()}",
        memory_id=memory_id,
        candidate_id=candidate_id,
        tenant_id=identity.tenant_id,
        workspace_id=identity.workspace_id,
        actor_subject_id=identity.subject_id,
        action=action,
        outcome=outcome,
        run_id=run_id,
        trace_id=trace_id,
        reason=reason,
        detail_json=json.dumps(detail or {}, ensure_ascii=False, sort_keys=True),
    )
    db.add(event)
    if commit:
        db.commit()
    return event
