import os
from datetime import UTC, datetime

import pytest
from redis import Redis
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.memory.contracts import MemoryScope, MemoryStatus, MemoryType, TrustLevel
from app.memory.deletion import MemoryDeletionService
from app.memory.models import (
    MEMORY_LIFECYCLE_TABLES,
    P2B_MEMORY_TABLES,
    MemoryDeleteVerification,
    MemoryRecord,
)
from app.memory.working import working_registry_key
from app.models.auth import User
from app.platform.identity import IdentityContextFactory


pytestmark = pytest.mark.no_db


def test_real_redis_cross_store_user_clear_and_verification():
    redis_url = os.getenv("MEMORY41_TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("MEMORY41_TEST_REDIS_URL is required for isolated Redis integration")
    engine = create_engine("sqlite:///:memory:")
    for table in [*P2B_MEMORY_TABLES, *MEMORY_LIFECYCLE_TABLES]:
        table.create(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    client = Redis.from_url(redis_url, decode_responses=True)
    user = User(
        id=4101,
        username="redis-memory-41",
        password_hash="x",
        display_name="Redis Memory 41",
        role="analyst_admin",
        region_code=None,
        is_active=True,
    )
    identity = IdentityContextFactory.from_user(user)
    memory_id = "MEM-41-REDIS-INTEGRATION"
    registry = working_registry_key(identity)
    working_key = "chatbi:working:v1:memory41-integration"
    client.set(f"memory:record:{memory_id}", "cached")
    client.set(working_key, "working-state")
    client.sadd(registry, working_key)
    try:
        with factory() as db:
            now = datetime.now(UTC)
            db.add(MemoryRecord(
                memory_id=memory_id,
                memory_type=MemoryType.SEMANTIC,
                scope_type=MemoryScope.USER,
                tenant_id=identity.tenant_id,
                organization_id=identity.org_id,
                workspace_id=identity.workspace_id,
                user_id=identity.subject_id,
                scenario_id="charging_ops",
                content="Redis integration memory",
                structured_value_json='{"key":"region","value":"R01"}',
                source_type="USER_STATEMENT",
                trust_level=TrustLevel.USER_CONFIRMED,
                confidence=1.0,
                importance=0.8,
                status=MemoryStatus.ACTIVE,
                version=1,
                duplicate_hash="redis41" + "0" * 57,
                retention_policy="STANDARD",
                approval_required=False,
                valid_from=now,
                created_at=now,
                updated_at=now,
            ))
            db.commit()
            result = MemoryDeletionService(
                db, identity, redis_client=client
            ).purge_current_user(reason="isolated Redis verification")
            assert result.verification_passed is True
            assert db.scalar(select(MemoryDeleteVerification).where(
                MemoryDeleteVerification.task_id == result.task_id,
                MemoryDeleteVerification.target_store == "REDIS",
            )).status == "VERIFIED"
        assert not client.exists(f"memory:record:{memory_id}")
        assert not client.exists(working_key)
        assert not client.exists(registry)
    finally:
        client.delete(
            f"memory:record:{memory_id}",
            f"memory:embedding:{memory_id}",
            working_key,
            registry,
        )
        client.close()
        engine.dispose()
