from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.memory.contracts import (
    LifecycleTaskStatus,
    LifecycleTaskType,
    MemoryScope,
    MemoryStatus,
    MemoryType,
    TrustLevel,
)
from app.memory.deletion import MemoryDeletionService
from app.memory.jobs import MemoryLifecycleTaskQueue
from app.memory.lifecycle import MemoryLifecycleService
from app.memory.models import (
    MEMORY_LIFECYCLE_TABLES,
    P2B_MEMORY_TABLES,
    MemoryDeleteVerification,
    MemoryLifecycleOutbox,
    MemoryLifecycleTask,
    MemoryRecord,
)
from app.memory.retrieval import MemoryRetriever
from app.memory.scheduler import MemoryLifecycleWorker, system_identity
from app.models.auth import User
from app.governance.models import LegalHold
from app.platform.identity import IdentityContextFactory


pytestmark = pytest.mark.no_db


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, object] = {}

    def smembers(self, key):
        value = self.data.get(key, set())
        return value if isinstance(value, set) else set()

    def delete(self, *keys):
        deleted = 0
        for key in keys:
            deleted += int(self.data.pop(key, None) is not None)
        return deleted

    def exists(self, key):
        return int(key in self.data)


class FakeStore:
    def __init__(self, values=(), *, fail_once=False) -> None:
        self.values = set(values)
        self.fail_once = fail_once

    def delete(self, resource_id):
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("injected transient failure")
        self.values.discard(resource_id)
        return True

    def exists(self, resource_id):
        return resource_id in self.values


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    for table in [*P2B_MEMORY_TABLES, *MEMORY_LIFECYCLE_TABLES]:
        table.create(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as session:
        yield session
    engine.dispose()


def identity(user_id=1):
    user = User(
        id=user_id,
        username=f"memory-{user_id}",
        password_hash="x",
        display_name="Memory User",
        role="analyst_admin",
        region_code=None,
        is_active=True,
    )
    return IdentityContextFactory.from_user(user)


def record(owner, *, memory_id="MEM-41-1", age_days=0, status=MemoryStatus.ACTIVE, legal_hold=False):
    now = datetime.now(UTC)
    return MemoryRecord(
        memory_id=memory_id,
        memory_type=MemoryType.SEMANTIC,
        scope_type=MemoryScope.USER,
        tenant_id=owner.tenant_id,
        organization_id=owner.org_id,
        workspace_id=owner.workspace_id,
        user_id=owner.subject_id,
        scenario_id="charging_ops",
        content="已确认结构化状态",
        structured_value_json='{"key":"active_region","value":"R01"}',
        source_type="USER_STATEMENT",
        trust_level=TrustLevel.USER_CONFIRMED,
        confidence=1.0,
        importance=0.8,
        status=status,
        version=1,
        duplicate_hash=(memory_id.lower() + "0" * 64)[:64],
        retention_policy="STANDARD",
        approval_required=False,
        legal_hold=legal_hold,
        valid_from=now - timedelta(days=age_days),
        created_at=now - timedelta(days=age_days),
        updated_at=now - timedelta(days=age_days),
    )


def test_scheduler_lifecycle_cold_cross_store_delete_and_verification(db):
    owner = identity()
    item = record(owner, age_days=100)
    db.add(item)
    queue = MemoryLifecycleTaskQueue(db, system_identity())
    task = queue.enqueue_maintenance(
        scenario_id="charging_ops", scheduled_for=datetime.now(UTC)
    )
    db.commit()
    redis = FakeRedis()
    redis.data[f"memory:record:{item.memory_id}"] = "cached"
    vector = FakeStore([item.memory_id])
    objects = FakeStore([item.memory_id])

    completed = MemoryLifecycleWorker(
        db,
        worker_id="test-worker",
        redis_client=redis,
        derived_index=vector,
        object_store=objects,
    ).run_once()

    assert completed.task_id == task.task_id
    assert completed.status == LifecycleTaskStatus.COMPLETED
    assert item.status == MemoryStatus.COLD
    assert not vector.exists(item.memory_id)
    assert not objects.exists(item.memory_id)
    stores = {row.target_store: row.status for row in db.scalars(select(
        MemoryDeleteVerification
    ).where(MemoryDeleteVerification.task_id == task.task_id)).all()}
    assert stores == {
        "OBJECT": "VERIFIED",
        "POSTGRESQL": "VERIFIED",
        "REDIS": "VERIFIED",
        "VECTOR": "VERIFIED",
    }


def test_recall_signal_restores_reduced_rank_only_after_authorized_query(db):
    owner = identity()
    item = record(owner, status=MemoryStatus.REDUCED_RANK)
    db.add(item)
    db.commit()

    result = MemoryRetriever(db, owner).retrieve(
        scenario_id="charging_ops", memory_types=(MemoryType.SEMANTIC,)
    )

    assert result.records == (item,)
    assert item.recall_count == 1
    assert item.last_recalled_at is not None
    assert item.status == MemoryStatus.ACTIVE


def test_outbox_retry_is_idempotent_and_eventually_verifies(db):
    owner = identity()
    item = record(owner)
    db.add(item)
    db.commit()
    vector = FakeStore([item.memory_id], fail_once=True)

    result = MemoryDeletionService(db, owner, derived_index=vector).delete_one(
        item.memory_id, reason="用户主动清除"
    )
    task = db.get(MemoryLifecycleTask, result.task_id)
    assert task.status == LifecycleTaskStatus.RETRY
    assert item.status == MemoryStatus.DELETED
    outbox = db.scalar(select(MemoryLifecycleOutbox).where(
        MemoryLifecycleOutbox.task_id == task.task_id,
        MemoryLifecycleOutbox.target_store == "VECTOR",
    ))
    outbox.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    task.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()

    rerun = MemoryLifecycleWorker(
        db, worker_id="retry-worker", derived_index=vector
    ).run_once()
    assert rerun.status == LifecycleTaskStatus.COMPLETED
    assert not vector.exists(item.memory_id)
    assert db.scalar(select(MemoryDeleteVerification).where(
        MemoryDeleteVerification.task_id == task.task_id,
        MemoryDeleteVerification.target_store == "VECTOR",
    )).status == "VERIFIED"


def test_forget_is_idempotent_and_legal_hold_is_audited_as_blocked(db):
    owner = identity()
    item = record(owner, legal_hold=True)
    db.add(item)
    db.commit()

    first = MemoryDeletionService(db, owner).delete_one(item.memory_id, reason="用户清除")
    second = MemoryDeletionService(db, owner).delete_one(item.memory_id, reason="用户清除")

    assert first.task_id == second.task_id
    assert first.legal_hold_count == second.legal_hold_count == 1
    assert item.status == MemoryStatus.ACTIVE
    task = db.get(MemoryLifecycleTask, first.task_id)
    assert task.status == LifecycleTaskStatus.BLOCKED
    assert task.failure_reason == "LEGAL_HOLD_BLOCKED"


def test_user_clear_deletes_working_registry_and_verifies_no_recall(db):
    owner = identity()
    item = record(owner)
    db.add(item)
    db.commit()
    from app.memory.working import working_registry_key

    redis = FakeRedis()
    registry = working_registry_key(owner)
    redis.data[registry] = {"working:key:1"}
    redis.data["working:key:1"] = "state"
    result = MemoryDeletionService(db, owner, redis_client=redis).purge_current_user(
        reason="用户账户记忆清除"
    )

    assert result.deleted_count == 1
    assert result.verification_passed is True
    assert not redis.data
    assert MemoryRetriever(db, owner).retrieve(
        scenario_id="charging_ops", memory_types=(MemoryType.SEMANTIC,)
    ).records == ()


def test_maintenance_enqueue_idempotency_uses_schedule_bucket(db):
    queue = MemoryLifecycleTaskQueue(db, system_identity())
    scheduled = datetime(2026, 8, 8, 12, 0, 30, tzinfo=UTC)
    first = queue.enqueue_maintenance(scenario_id="charging_ops", scheduled_for=scheduled)
    second = queue.enqueue_maintenance(scenario_id="charging_ops", scheduled_for=scheduled)
    assert first.task_id == second.task_id


def test_worker_completes_durable_forget_after_request_process_crash(db):
    owner = identity()
    item = record(owner, memory_id="MEM-41-CRASH-RECOVERY")
    db.add(item)
    task = MemoryLifecycleTaskQueue(db, owner).enqueue(
        task_type=LifecycleTaskType.FORGET_MEMORY,
        idempotency_key="forget-crash-recovery",
        reason="durable request",
        memory_id=item.memory_id,
        user_id=owner.subject_id,
        scenario_id="charging_ops",
        payload={"resource_ids": [item.memory_id]},
    )
    db.commit()

    completed = MemoryLifecycleWorker(db, worker_id="crash-recovery-worker").run_once()

    assert completed.task_id == task.task_id
    assert completed.status == LifecycleTaskStatus.COMPLETED
    assert item.status == MemoryStatus.DELETED
    assert item.content == "[DELETED]"


def test_worker_reclaims_stale_running_task_lease(db):
    owner = identity()
    item = record(owner, memory_id="MEM-41-STALE-LEASE")
    db.add(item)
    task = MemoryLifecycleTaskQueue(db, owner).enqueue(
        task_type=LifecycleTaskType.FORGET_MEMORY,
        idempotency_key="forget-stale-lease",
        reason="stale worker recovery",
        memory_id=item.memory_id,
        user_id=owner.subject_id,
        scenario_id="charging_ops",
        payload={"resource_ids": [item.memory_id]},
    )
    task.status = LifecycleTaskStatus.RUNNING
    task.locked_by = "dead-worker"
    task.locked_at = datetime.now(UTC) - timedelta(minutes=10)
    db.commit()

    completed = MemoryLifecycleWorker(db, worker_id="lease-recovery-worker").run_once()

    assert completed.task_id == task.task_id
    assert completed.status == LifecycleTaskStatus.COMPLETED
    assert item.status == MemoryStatus.DELETED


def test_governed_legal_hold_blocks_ttl_transition():
    engine = create_engine("sqlite:///:memory:")
    for table in [*P2B_MEMORY_TABLES, *MEMORY_LIFECYCLE_TABLES, LegalHold.__table__]:
        table.create(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    owner = identity()
    now = datetime.now(UTC)
    with factory() as session:
        item = record(
            owner,
            memory_id="MEM-41-GOVERNED-HOLD",
            age_days=100,
        )
        item.expires_at = now - timedelta(days=1)
        session.add_all([
            item,
            LegalHold(
                legal_hold_id="HOLD-MEM-41",
                tenant_id=owner.tenant_id,
                workspace_id=owner.workspace_id,
                resource_type="memory",
                resource_id=item.memory_id,
                user_id=owner.subject_id,
                memory_type=MemoryType.SEMANTIC,
                reason_code="TEST_HOLD",
                reason="governed legal hold integration",
                status="ACTIVE",
                created_by="system:test",
            ),
        ])
        session.commit()

        result = MemoryLifecycleService(session, owner).maintain(
            scenario_id="charging_ops", now=now
        )

        assert result.expired == result.cold == 0
        assert item.status == MemoryStatus.ACTIVE
    engine.dispose()
