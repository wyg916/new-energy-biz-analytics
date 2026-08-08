from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.memory.audit import audit_memory_use
from app.memory.contracts import (
    DeleteVerificationStatus,
    LifecycleTaskStatus,
    LifecycleTaskType,
    MemoryStatus,
    OutboxStatus,
)
from app.memory.models import (
    MemoryDeleteVerification,
    MemoryLifecycleOutbox,
    MemoryLifecycleTask,
    MemoryRecord,
)
from app.memory.stores import DeleteStore, store_registry
from app.platform.identity import IdentityContext


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _resource_hash(resource_id: str) -> str:
    return hashlib.sha256(resource_id.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DispatchResult:
    completed: int
    retrying: int
    failed: int
    verified: bool


class MemoryLifecycleTaskQueue:
    def __init__(self, db: Session, identity: IdentityContext) -> None:
        self.db = db
        self.identity = identity

    def enqueue(
        self,
        *,
        task_type: LifecycleTaskType,
        idempotency_key: str,
        reason: str,
        memory_id: str | None = None,
        user_id: str | None = None,
        scenario_id: str | None = None,
        payload: dict | None = None,
        max_attempts: int = 5,
    ) -> MemoryLifecycleTask:
        existing = self.db.scalar(select(MemoryLifecycleTask).where(
            MemoryLifecycleTask.idempotency_key == idempotency_key
        ))
        if existing is not None:
            return existing
        now = datetime.now(UTC)
        task = MemoryLifecycleTask(
            task_id=f"MEMTASK-{uuid4()}",
            task_type=task_type,
            status=LifecycleTaskStatus.PENDING,
            tenant_id=self.identity.tenant_id,
            organization_id=self.identity.org_id,
            workspace_id=self.identity.workspace_id,
            requested_by=self.identity.subject_id,
            memory_id=memory_id,
            user_id=user_id,
            scenario_id=scenario_id,
            reason=reason[:500],
            payload_json=json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
            idempotency_key=idempotency_key[:160],
            max_attempts=max(1, min(max_attempts, 20)),
            next_attempt_at=now,
            created_at=now,
            updated_at=now,
        )
        self.db.add(task)
        try:
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            existing = self.db.scalar(select(MemoryLifecycleTask).where(
                MemoryLifecycleTask.idempotency_key == idempotency_key
            ))
            if existing is None:
                raise
            return existing
        audit_memory_use(
            self.db,
            self.identity,
            action="memory.lifecycle.task_enqueued",
            outcome="success",
            memory_id=memory_id,
            reason=reason,
            detail={"task_id": task.task_id, "task_type": task_type},
        )
        return task

    def enqueue_maintenance(self, *, scenario_id: str, scheduled_for: datetime) -> MemoryLifecycleTask:
        bucket = scheduled_for.astimezone(UTC).replace(second=0, microsecond=0).isoformat()
        return self.enqueue(
            task_type=LifecycleTaskType.MAINTAIN,
            idempotency_key=f"maintain:{self.identity.tenant_id}:{self.identity.workspace_id}:{scenario_id}:{bucket}",
            reason="scheduled lifecycle maintenance",
            scenario_id=scenario_id,
            payload={"scheduled_for": scheduled_for.isoformat()},
        )


class CrossStoreDeleteCoordinator:
    def __init__(
        self,
        db: Session,
        identity: IdentityContext,
        *,
        redis_client=None,
        derived_index=None,
        object_store=None,
    ) -> None:
        self.db = db
        self.identity = identity
        self.stores = store_registry(
            redis_client=redis_client,
            derived_index=derived_index,
            object_store=object_store,
        )

    def ensure_outbox(self, task: MemoryLifecycleTask, resource_ids: list[str]) -> None:
        now = datetime.now(UTC)
        for resource_id in sorted(set(resource_ids)):
            for name, store in self.stores.items():
                existing = self.db.scalar(select(MemoryLifecycleOutbox).where(
                    MemoryLifecycleOutbox.task_id == task.task_id,
                    MemoryLifecycleOutbox.target_store == name,
                    MemoryLifecycleOutbox.operation == "DELETE",
                    MemoryLifecycleOutbox.resource_id == resource_id,
                ))
                if existing is None and store.configured:
                    self.db.add(MemoryLifecycleOutbox(
                        event_id=f"MEMOUT-{uuid4()}",
                        task_id=task.task_id,
                        operation="DELETE",
                        target_store=name,
                        resource_id=resource_id,
                        status=OutboxStatus.PENDING,
                        max_attempts=task.max_attempts,
                        next_attempt_at=now,
                        created_at=now,
                        updated_at=now,
                    ))
        self.db.flush()

    def ensure_store_outbox(
        self, task: MemoryLifecycleTask, *, target_store: str, resource_ids: list[str]
    ) -> None:
        store = self.stores[target_store]
        if not store.configured:
            return
        now = datetime.now(UTC)
        for resource_id in sorted(set(resource_ids)):
            existing = self.db.scalar(select(MemoryLifecycleOutbox).where(
                MemoryLifecycleOutbox.task_id == task.task_id,
                MemoryLifecycleOutbox.target_store == target_store,
                MemoryLifecycleOutbox.operation == "DELETE",
                MemoryLifecycleOutbox.resource_id == resource_id,
            ))
            if existing is None:
                self.db.add(MemoryLifecycleOutbox(
                    event_id=f"MEMOUT-{uuid4()}",
                    task_id=task.task_id,
                    operation="DELETE",
                    target_store=target_store,
                    resource_id=resource_id,
                    status=OutboxStatus.PENDING,
                    max_attempts=task.max_attempts,
                    next_attempt_at=now,
                    created_at=now,
                    updated_at=now,
                ))
        self.db.flush()

    def dispatch_and_verify(self, task: MemoryLifecycleTask, resource_ids: list[str]) -> DispatchResult:
        now = datetime.now(UTC)
        completed = retrying = failed = 0
        events = self.db.scalars(select(MemoryLifecycleOutbox).where(
            MemoryLifecycleOutbox.task_id == task.task_id,
            MemoryLifecycleOutbox.status.in_((OutboxStatus.PENDING, OutboxStatus.RETRY, OutboxStatus.RUNNING)),
            MemoryLifecycleOutbox.next_attempt_at <= now,
        )).all()
        for event in events:
            store = self.stores[event.target_store]
            event.status = OutboxStatus.RUNNING
            event.attempt_count += 1
            event.updated_at = now
            try:
                if not store.delete(event.resource_id):
                    raise RuntimeError(f"{event.target_store}_DELETE_NOT_CONFIRMED")
                event.status = OutboxStatus.COMPLETED
                event.delivered_at = now
                event.failure_reason = None
                completed += 1
            except Exception as exc:
                event.failure_reason = f"{type(exc).__name__}: {exc}"[:500]
                if event.attempt_count >= event.max_attempts:
                    event.status = OutboxStatus.FAILED
                    failed += 1
                else:
                    event.status = OutboxStatus.RETRY
                    event.next_attempt_at = now + timedelta(seconds=min(2 ** event.attempt_count, 300))
                    retrying += 1
        # SessionLocal intentionally disables autoflush; persist delivery states
        # before the aggregate queries decide whether verification may run.
        self.db.flush()
        pending = self.db.scalar(select(func.count()).select_from(MemoryLifecycleOutbox).where(
            MemoryLifecycleOutbox.task_id == task.task_id,
            MemoryLifecycleOutbox.status.in_((OutboxStatus.PENDING, OutboxStatus.RETRY, OutboxStatus.RUNNING)),
        )) or 0
        hard_failed = self.db.scalar(select(func.count()).select_from(MemoryLifecycleOutbox).where(
            MemoryLifecycleOutbox.task_id == task.task_id,
            MemoryLifecycleOutbox.status == OutboxStatus.FAILED,
        )) or 0
        verified = False
        if pending == 0 and hard_failed == 0:
            verified = self.verify(task, resource_ids)
        if hard_failed:
            task.status = LifecycleTaskStatus.FAILED
            task.failure_reason = "cross-store delete exhausted retries"
            task.finished_at = now
        elif pending or not verified:
            task.status = LifecycleTaskStatus.RETRY
            task.next_attempt_at = now + timedelta(seconds=min(2 ** max(task.attempt_count, 1), 300))
            task.failure_reason = "delete verification pending" if not pending else "cross-store delete pending"
        else:
            task.status = LifecycleTaskStatus.COMPLETED
            task.failure_reason = None
            task.finished_at = now
        task.updated_at = now
        self.db.flush()
        return DispatchResult(completed, retrying, failed, verified)

    def verify(self, task: MemoryLifecycleTask, resource_ids: list[str]) -> bool:
        statuses: dict[str, str] = {}
        records = self.db.scalars(select(MemoryRecord).where(
            MemoryRecord.memory_id.in_(resource_ids)
        )).all() if resource_ids else []
        by_id = {row.memory_id: row for row in records}
        no_recall = all(
            resource_id not in by_id
            or by_id[resource_id].deleted_at is not None
            or by_id[resource_id].status in {
                MemoryStatus.COLD, MemoryStatus.ARCHIVED, MemoryStatus.REVOKED, MemoryStatus.DELETED
            }
            for resource_id in resource_ids
        )
        statuses["POSTGRESQL"] = (
            DeleteVerificationStatus.VERIFIED if no_recall else DeleteVerificationStatus.PRESENT
        )
        for name, store in self.stores.items():
            if not store.configured:
                statuses[name] = DeleteVerificationStatus.NOT_CONFIGURED
                continue
            try:
                store_resource_ids = list(self.db.scalars(select(
                    MemoryLifecycleOutbox.resource_id
                ).where(
                    MemoryLifecycleOutbox.task_id == task.task_id,
                    MemoryLifecycleOutbox.target_store == name,
                )).all())
                statuses[name] = (
                    DeleteVerificationStatus.VERIFIED
                    if all(store.absent(resource_id) for resource_id in store_resource_ids)
                    else DeleteVerificationStatus.PRESENT
                )
            except Exception:
                statuses[name] = DeleteVerificationStatus.ERROR
        now = datetime.now(UTC)
        digest = _resource_hash("|".join(sorted(resource_ids)))
        for name, status in statuses.items():
            row = self.db.scalar(select(MemoryDeleteVerification).where(
                MemoryDeleteVerification.task_id == task.task_id,
                MemoryDeleteVerification.target_store == name,
            ))
            if row is None:
                row = MemoryDeleteVerification(
                    verification_id=f"MEMVERIFY-{uuid4()}",
                    task_id=task.task_id,
                    target_store=name,
                    resource_id_hash=digest,
                    status=status,
                    checked_at=now,
                )
                self.db.add(row)
            else:
                row.status = status
                row.checked_at = now
            row.detail_json = json.dumps(
                {"resource_count": len(resource_ids), "no_recall": status == DeleteVerificationStatus.VERIFIED},
                sort_keys=True,
            )
        audit_memory_use(
            self.db,
            self.identity,
            action="memory.delete.verify",
            outcome="success" if all(value in {
                DeleteVerificationStatus.VERIFIED, DeleteVerificationStatus.NOT_CONFIGURED
            } for value in statuses.values()) else "pending",
            detail={"task_id": task.task_id, "stores": statuses},
        )
        return all(value in {
            DeleteVerificationStatus.VERIFIED, DeleteVerificationStatus.NOT_CONFIGURED
        } for value in statuses.values())


def due_task_query(now: datetime):
    return select(MemoryLifecycleTask).where(
        or_(
            (
                MemoryLifecycleTask.status.in_((LifecycleTaskStatus.PENDING, LifecycleTaskStatus.RETRY))
                & (MemoryLifecycleTask.next_attempt_at <= now)
            ),
            (
                (MemoryLifecycleTask.status == LifecycleTaskStatus.RUNNING)
                & (MemoryLifecycleTask.locked_at <= now - timedelta(minutes=5))
            ),
        )
    ).order_by(MemoryLifecycleTask.next_attempt_at, MemoryLifecycleTask.created_at)
