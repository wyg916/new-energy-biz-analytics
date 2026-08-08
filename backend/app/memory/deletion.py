from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.memory.audit import audit_memory_use
from app.memory.authorization import MemoryAuthorization, MemoryAuthorizationError
from app.memory.contracts import LifecycleTaskStatus, LifecycleTaskType, MemoryStatus
from app.memory.jobs import CrossStoreDeleteCoordinator, MemoryLifecycleTaskQueue
from app.memory.models import MemoryDeletionAudit, MemoryRecord, MemoryWriteCandidateRecord
from app.memory.working import working_registry_key
from app.platform.identity import IdentityContext
from app.governance.retention import DeletionGovernance


class RedisDeletionClient(Protocol):
    def smembers(self, key: str): ...
    def delete(self, *keys: str) -> int: ...


class DerivedMemoryIndex(Protocol):
    def delete(self, memory_id: str) -> bool: ...
    def exists(self, memory_id: str) -> bool: ...


class ObjectMemoryStore(Protocol):
    def delete(self, memory_id: str) -> bool: ...
    def exists(self, memory_id: str) -> bool: ...


@dataclass(frozen=True)
class DeletionResult:
    deleted_count: int
    legal_hold_count: int
    redis_deleted_count: int
    derived_deleted_count: int
    retention_blocked_count: int = 0
    task_id: str | None = None
    verification_passed: bool = False


class MemoryDeletionService:
    def __init__(
        self,
        db: Session,
        identity: IdentityContext,
        *,
        redis_client: RedisDeletionClient | None = None,
        derived_index: DerivedMemoryIndex | None = None,
        object_store: ObjectMemoryStore | None = None,
    ) -> None:
        self.db = db
        self.identity = identity
        self.redis_client = redis_client
        self.derived_index = derived_index
        self.object_store = object_store

    def delete_one(self, memory_id: str, *, reason: str) -> DeletionResult:
        record = self.db.get(MemoryRecord, memory_id)
        if record is None:
            return DeletionResult(0, 0, 0, 0)
        MemoryAuthorization.assert_owned(self.identity, record)
        task = MemoryLifecycleTaskQueue(self.db, self.identity).enqueue(
            task_type=LifecycleTaskType.FORGET_MEMORY,
            idempotency_key=f"forget-memory:{record.tenant_id}:{record.workspace_id}:{memory_id}",
            reason=reason,
            memory_id=memory_id,
            user_id=record.user_id,
            scenario_id=record.scenario_id,
            payload={"resource_ids": [memory_id]},
        )
        # Persist the durable request before evaluating governance or touching any store.
        self.db.commit()
        if task.status == LifecycleTaskStatus.COMPLETED:
            result = json.loads(task.result_json or "{}")
            return DeletionResult(**result)
        task.status = LifecycleTaskStatus.RUNNING
        task.attempt_count += 1
        governance = self._governance_decision(record)
        if record.legal_hold or governance.code == "LEGAL_HOLD_BLOCKED":
            task.status = LifecycleTaskStatus.BLOCKED
            task.failure_reason = "LEGAL_HOLD_BLOCKED"
            task.finished_at = datetime.now(UTC)
            self._audit_deletion(record, reason=reason, legal_hold=True, derived_deleted=False, working_deleted=False)
            self.db.commit()
            return DeletionResult(0, 1, 0, 0, task_id=task.task_id)
        if governance.code == "RETENTION_POLICY_BLOCKED":
            task.status = LifecycleTaskStatus.BLOCKED
            task.failure_reason = "RETENTION_POLICY_BLOCKED"
            task.finished_at = datetime.now(UTC)
            self._audit_deletion(record, reason=reason, legal_hold=False, derived_deleted=False, working_deleted=False)
            self.db.commit()
            return DeletionResult(0, 0, 0, 0, 1, task_id=task.task_id)
        self._anonymize(record)
        coordinator = CrossStoreDeleteCoordinator(
            self.db,
            self.identity,
            redis_client=self.redis_client,
            derived_index=self.derived_index,
            object_store=self.object_store,
        )
        coordinator.ensure_outbox(task, [memory_id])
        dispatch = coordinator.dispatch_and_verify(task, [memory_id])
        derived_deleted = self.derived_index is None or dispatch.failed == 0
        self._audit_deletion(
            record,
            reason=reason,
            legal_hold=False,
            derived_deleted=derived_deleted,
            working_deleted=False,
        )
        result = DeletionResult(
            1, 0, 0, int(bool(self.derived_index) and derived_deleted), 0,
            task_id=task.task_id,
            verification_passed=dispatch.verified,
        )
        task.result_json = json.dumps(result.__dict__, ensure_ascii=False, sort_keys=True)
        audit_memory_use(
            self.db,
            self.identity,
            action="memory.delete",
            outcome="success",
            memory_id=memory_id,
            reason=reason,
        )
        self.db.commit()
        return result

    def purge_current_user(self, *, reason: str) -> DeletionResult:
        records = self.db.scalars(select(MemoryRecord).where(
            MemoryRecord.tenant_id == self.identity.tenant_id,
            MemoryRecord.organization_id == self.identity.org_id,
            MemoryRecord.workspace_id == self.identity.workspace_id,
            MemoryRecord.user_id == self.identity.subject_id,
            MemoryRecord.deleted_at.is_(None),
        )).all()
        resource_ids = sorted(record.memory_id for record in records)
        resource_digest = hashlib.sha256("|".join(resource_ids).encode("utf-8")).hexdigest()
        task = MemoryLifecycleTaskQueue(self.db, self.identity).enqueue(
            task_type=LifecycleTaskType.FORGET_USER,
            idempotency_key=f"forget-user:{self.identity.tenant_id}:{self.identity.workspace_id}:{self.identity.subject_id}:{resource_digest}",
            reason=reason,
            user_id=self.identity.subject_id,
            payload={"resource_ids": resource_ids},
        )
        self.db.commit()
        if task.status == LifecycleTaskStatus.COMPLETED:
            return DeletionResult(**json.loads(task.result_json or "{}"))
        task.status = LifecycleTaskStatus.RUNNING
        task.attempt_count += 1
        deleted = held = derived_deleted_count = retention_blocked = 0
        deletable_ids: list[str] = []
        for record in records:
            governance = self._governance_decision(record)
            if record.legal_hold or governance.code == "LEGAL_HOLD_BLOCKED":
                held += 1
                self._audit_deletion(record, reason=reason, legal_hold=True, derived_deleted=False, working_deleted=False)
                continue
            if governance.code == "RETENTION_POLICY_BLOCKED":
                retention_blocked += 1
                self._audit_deletion(record, reason=reason, legal_hold=False, derived_deleted=False, working_deleted=False)
                continue
            self._anonymize(record)
            deletable_ids.append(record.memory_id)
            self._audit_deletion(
                record,
                reason=reason,
                legal_hold=False,
                derived_deleted=False,
                working_deleted=True,
            )
            deleted += 1
        candidates = self.db.scalars(select(MemoryWriteCandidateRecord).where(
            MemoryWriteCandidateRecord.tenant_id == self.identity.tenant_id,
            MemoryWriteCandidateRecord.workspace_id == self.identity.workspace_id,
            MemoryWriteCandidateRecord.user_id == self.identity.subject_id,
        )).all()
        for candidate in candidates:
            self.db.delete(candidate)
        redis_deleted = self._clear_working_registry()
        coordinator = CrossStoreDeleteCoordinator(
            self.db,
            self.identity,
            redis_client=self.redis_client,
            derived_index=self.derived_index,
            object_store=self.object_store,
        )
        task.payload_json = json.dumps({"resource_ids": deletable_ids}, sort_keys=True)
        coordinator.ensure_outbox(task, deletable_ids)
        coordinator.ensure_store_outbox(
            task,
            target_store="REDIS",
            resource_ids=[f"working-registry::{working_registry_key(self.identity)}"],
        )
        dispatch = coordinator.dispatch_and_verify(task, deletable_ids)
        derived_deleted_count = len(deletable_ids) if self.derived_index is not None and dispatch.failed == 0 else 0
        audit_memory_use(
            self.db,
            self.identity,
            action="memory.delete_user",
            outcome="success",
            reason=reason,
            detail={
                "deleted_count": deleted,
                "legal_hold_count": held,
                "candidate_deleted_count": len(candidates),
                "redis_deleted_count": redis_deleted,
                "retention_blocked_count": retention_blocked,
            },
        )
        result = DeletionResult(
            deleted, held, redis_deleted, derived_deleted_count, retention_blocked,
            task_id=task.task_id,
            verification_passed=dispatch.verified,
        )
        task.result_json = json.dumps(result.__dict__, ensure_ascii=False, sort_keys=True)
        self.db.commit()
        return result

    def _governance_decision(self, record: MemoryRecord):
        if not inspect(self.db.get_bind()).has_table("legal_hold"):
            from app.governance.retention import DeletionGovernanceDecision
            return DeletionGovernanceDecision(True, "DELETE_ALLOWED")
        return DeletionGovernance(self.db, self.identity).evaluate(
            resource_type="memory",
            resource_id=record.memory_id,
            user_id=record.user_id,
            memory_type=record.memory_type,
            created_at=record.created_at,
        )

    @staticmethod
    def _anonymize(record: MemoryRecord) -> None:
        record.content = "[DELETED]"
        record.structured_value_json = "{}"
        record.source_id = None
        record.status = MemoryStatus.DELETED
        record.valid_to = datetime.now(UTC)
        record.deleted_at = datetime.now(UTC)
        record.updated_at = datetime.now(UTC)

    def _clear_working_registry(self) -> int:
        if self.redis_client is None:
            return 0
        registry = working_registry_key(self.identity)
        try:
            keys = list(self.redis_client.smembers(registry) or ())
            normalized = [item.decode("utf-8") if isinstance(item, bytes) else item for item in keys]
            targets = [*normalized, registry]
            return self.redis_client.delete(*targets) if targets else 0
        except Exception:
            return 0

    def _audit_deletion(
        self,
        record: MemoryRecord,
        *,
        reason: str,
        legal_hold: bool,
        derived_deleted: bool,
        working_deleted: bool,
    ) -> None:
        self.db.add(MemoryDeletionAudit(
            deletion_id=f"MEMDEL-{uuid4()}",
            memory_id_hash=hashlib.sha256(record.memory_id.encode("utf-8")).hexdigest(),
            tenant_id=record.tenant_id,
            workspace_id=record.workspace_id,
            user_id=record.user_id,
            requested_by=self.identity.subject_id,
            deletion_mode="LEGAL_HOLD_RETAINED" if legal_hold else "ANONYMIZED",
            derived_index_deleted=derived_deleted,
            working_memory_deleted=working_deleted,
            legal_hold_applied=legal_hold,
            reason=reason[:500],
        ))
