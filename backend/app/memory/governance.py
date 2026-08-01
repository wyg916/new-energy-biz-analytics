from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy.orm import Session

from app.memory.authorization import MemoryAuthorization
from app.memory.contracts import MemoryScope, MemoryStatus, MemoryType, TrustLevel
from app.memory.models import MemoryRecord
from app.platform.identity import IdentityContext


def record_governance_meta(
    db: Session,
    identity: IdentityContext,
    *,
    action: str,
    governed_memory_id: str | None,
    run_id: str | None,
    scenario_id: str | None,
    detail: dict,
) -> MemoryRecord:
    scope = MemoryAuthorization.scope_from_identity(
        identity,
        MemoryScope.WORKSPACE,
        scenario_id=scenario_id,
        run_id=run_id,
    )
    record = MemoryRecord(
        memory_id=f"MEMGOV-{uuid4()}",
        memory_type=MemoryType.GOVERNANCE,
        scope_type=scope.scope_type,
        tenant_id=scope.tenant_id,
        organization_id=scope.organization_id,
        workspace_id=scope.workspace_id,
        run_id=run_id,
        scenario_id=scenario_id,
        content=action,
        structured_value_json=json.dumps(
            {"governed_memory_id": governed_memory_id, "detail": detail},
            ensure_ascii=False,
            sort_keys=True,
        ),
        source_type="SYSTEM_GOVERNANCE",
        source_id=governed_memory_id,
        trust_level=TrustLevel.SYSTEM_VERIFIED,
        confidence=1.0,
        importance=1.0,
        status=MemoryStatus.ACTIVE,
        version=1,
        duplicate_hash=f"{uuid4().hex}{uuid4().hex}",
        retention_policy="AUDIT",
        approval_required=False,
    )
    db.add(record)
    return record
