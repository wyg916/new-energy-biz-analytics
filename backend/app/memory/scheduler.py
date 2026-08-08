from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.memory.audit import audit_memory_use
from app.memory.contracts import LifecycleTaskStatus, LifecycleTaskType
from app.memory.jobs import CrossStoreDeleteCoordinator, MemoryLifecycleTaskQueue, due_task_query
from app.memory.lifecycle import MemoryLifecycleService
from app.memory.metrics import memory_lifecycle_metrics
from app.memory.models import MemoryLifecycleTask
from app.memory.models import MemoryRecord
from app.platform.identity import IdentityContext


logger = logging.getLogger("app.memory.lifecycle")


def system_identity() -> IdentityContext:
    settings = get_settings()
    return IdentityContext(
        subject_id="system:memory-lifecycle",
        tenant_id=settings.platform_tenant_id,
        org_id=settings.platform_org_id,
        workspace_id=settings.platform_workspace_id,
        roles=("analyst_admin",),
        groups=(),
        data_scopes=("workspace:all",),
        auth_strength="internal-scheduler",
        issued_at=datetime.now(UTC),
        request_id=f"MEMSCHED-{uuid4()}",
        principal_id="system:memory-lifecycle",
        provider_code="INTERNAL",
    )


class MemoryLifecycleWorker:
    def __init__(
        self,
        db: Session,
        *,
        worker_id: str,
        redis_client=None,
        derived_index=None,
        object_store=None,
        identity: IdentityContext | None = None,
    ) -> None:
        self.db = db
        self.worker_id = worker_id
        self.identity = identity or system_identity()
        self.redis_client = redis_client
        self.derived_index = derived_index
        self.object_store = object_store

    def run_once(self, *, now: datetime | None = None) -> MemoryLifecycleTask | None:
        current = now or datetime.now(UTC)
        task = self.db.scalar(due_task_query(current).with_for_update(skip_locked=True).limit(1))
        if task is None:
            return None
        task.status = LifecycleTaskStatus.RUNNING
        task.locked_by = self.worker_id
        task.locked_at = current
        task.attempt_count += 1
        task.updated_at = current
        self.db.commit()
        transitions: dict[str, int] = {}
        try:
            payload = json.loads(task.payload_json or "{}")
            resource_ids = list(payload.get("resource_ids") or [])
            if task.task_type == LifecycleTaskType.MAINTAIN:
                result = MemoryLifecycleService(self.db, self.identity).maintain(
                    scenario_id=task.scenario_id or "charging_ops",
                    now=current,
                    system_scope=True,
                )
                transitions = {
                    "expired": result.expired,
                    "archived": result.archived,
                    "decayed": result.decayed,
                    "reduced_rank": result.reduced_rank,
                    "cold": result.cold,
                }
                resource_ids = list(result.no_recall_ids)
                payload["resource_ids"] = resource_ids
                task.payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
                task.result_json = json.dumps(transitions, ensure_ascii=False, sort_keys=True)
            elif task.task_type in {
                LifecycleTaskType.FORGET_MEMORY,
                LifecycleTaskType.FORGET_USER,
            }:
                from app.memory.deletion import MemoryDeletionService

                deletion = MemoryDeletionService(self.db, self.identity)
                records = self.db.scalars(select(MemoryRecord).where(
                    MemoryRecord.memory_id.in_(resource_ids),
                    MemoryRecord.tenant_id == task.tenant_id,
                    MemoryRecord.organization_id == task.organization_id,
                    MemoryRecord.workspace_id == task.workspace_id,
                )).all() if resource_ids else []
                for record in records:
                    if task.user_id and record.user_id != task.user_id:
                        raise PermissionError("FORGET_TASK_SCOPE_MISMATCH")
                    if record.deleted_at is not None:
                        continue
                    decision = deletion._governance_decision(record)
                    if record.legal_hold or decision.code == "LEGAL_HOLD_BLOCKED":
                        task.status = LifecycleTaskStatus.BLOCKED
                        task.failure_reason = "LEGAL_HOLD_BLOCKED"
                        task.finished_at = datetime.now(UTC)
                        task.locked_by = None
                        task.locked_at = None
                        audit_memory_use(
                            self.db,
                            self.identity,
                            action="memory.lifecycle.forget_blocked",
                            outcome="blocked",
                            memory_id=record.memory_id,
                            reason="LEGAL_HOLD_BLOCKED",
                            detail={"task_id": task.task_id},
                        )
                        self.db.commit()
                        memory_lifecycle_metrics.observe_run("BLOCKED")
                        return task
                    if decision.code == "RETENTION_POLICY_BLOCKED":
                        task.status = LifecycleTaskStatus.BLOCKED
                        task.failure_reason = "RETENTION_POLICY_BLOCKED"
                        task.finished_at = datetime.now(UTC)
                        task.locked_by = None
                        task.locked_at = None
                        self.db.commit()
                        memory_lifecycle_metrics.observe_run("BLOCKED")
                        return task
                    deletion._anonymize(record)
                self.db.flush()
            elif task.task_type != LifecycleTaskType.VERIFY_DELETE:
                raise RuntimeError(f"UNSUPPORTED_LIFECYCLE_TASK:{task.task_type}")
            coordinator = CrossStoreDeleteCoordinator(
                self.db,
                self.identity,
                redis_client=self.redis_client,
                derived_index=self.derived_index,
                object_store=self.object_store,
            )
            coordinator.ensure_outbox(task, resource_ids)
            coordinator.dispatch_and_verify(task, resource_ids)
            task.locked_by = None
            task.locked_at = None
            self.db.commit()
            memory_lifecycle_metrics.observe_run(
                str(task.status), transitions=transitions, timestamp=time.time()
            )
            return task
        except Exception as exc:
            self.db.rollback()
            task = self.db.get(MemoryLifecycleTask, task.task_id)
            if task is None:
                raise
            task.failure_reason = f"{type(exc).__name__}: {exc}"[:500]
            task.locked_by = None
            task.locked_at = None
            task.updated_at = datetime.now(UTC)
            if task.attempt_count >= task.max_attempts:
                task.status = LifecycleTaskStatus.FAILED
                task.finished_at = task.updated_at
            else:
                task.status = LifecycleTaskStatus.RETRY
                task.next_attempt_at = task.updated_at + timedelta(seconds=min(2 ** task.attempt_count, 300))
            audit_memory_use(
                self.db,
                self.identity,
                action="memory.lifecycle.task_failed",
                outcome=str(task.status),
                reason=task.failure_reason,
                detail={"task_id": task.task_id, "attempt_count": task.attempt_count},
            )
            self.db.commit()
            memory_lifecycle_metrics.observe_run(str(task.status))
            return task


class MemoryLifecycleScheduler:
    def __init__(self) -> None:
        settings = get_settings()
        self.interval_seconds = settings.memory_lifecycle_interval_seconds
        self.batch_size = settings.memory_lifecycle_batch_size
        self._stop = asyncio.Event()
        self.worker_id = f"memory-worker:{uuid4()}"

    def tick(self) -> int:
        identity = system_identity()
        redis_client = None
        try:
            settings = get_settings()
            if settings.memory_lifecycle_redis_enabled:
                redis_client = Redis.from_url(
                    settings.redis_url,
                    socket_connect_timeout=1,
                    socket_timeout=1,
                    decode_responses=True,
                )
            with SessionLocal() as db:
                queue = MemoryLifecycleTaskQueue(db, identity)
                now = datetime.now(UTC)
                for scenario_id in settings.memory_lifecycle_scenarios:
                    queue.enqueue_maintenance(scenario_id=scenario_id, scheduled_for=now)
                db.commit()
                worker = MemoryLifecycleWorker(
                    db, worker_id=self.worker_id, redis_client=redis_client, identity=identity
                )
                processed = 0
                for _ in range(self.batch_size):
                    if worker.run_once(now=now) is None:
                        break
                    processed += 1
                return processed
        finally:
            if redis_client is not None:
                redis_client.close()

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.to_thread(self.tick)
            except Exception:
                logger.exception("memory_lifecycle_scheduler_tick_failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_seconds)
            except TimeoutError:
                pass

    def stop(self) -> None:
        self._stop.set()
