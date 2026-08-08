from datetime import UTC, datetime

from sqlalchemy import select

from app.core.database import SessionLocal
from app.memory.contracts import MemoryScope, MemoryStatus, MemoryType, TrustLevel
from app.memory.models import MemoryDeleteVerification, MemoryLifecycleOutbox, MemoryRecord
from app.models.auth import User
from app.platform.identity import IdentityContextFactory


def test_postgres_forget_api_persists_task_audit_and_delete_verification(client, login):
    headers = login()
    with SessionLocal() as db:
        analyst = db.scalar(select(User).where(User.username == "analyst"))
        identity = IdentityContextFactory.from_user(analyst)
        now = datetime.now(UTC)
        db.add(MemoryRecord(
            memory_id="MEM-PG-41-DELETE",
            memory_type=MemoryType.SEMANTIC,
            scope_type=MemoryScope.USER,
            tenant_id=identity.tenant_id,
            organization_id=identity.org_id,
            workspace_id=identity.workspace_id,
            user_id=identity.subject_id,
            scenario_id="charging_ops",
            content="PostgreSQL integration memory",
            structured_value_json='{"key":"region","value":"R01"}',
            source_type="USER_STATEMENT",
            trust_level=TrustLevel.USER_CONFIRMED,
            confidence=1.0,
            importance=0.8,
            status=MemoryStatus.ACTIVE,
            version=1,
            duplicate_hash="pg41" + "0" * 60,
            retention_policy="STANDARD",
            approval_required=False,
            valid_from=now,
            created_at=now,
            updated_at=now,
        ))
        db.commit()

    response = client.delete(
        "/api/v1/memory/records/MEM-PG-41-DELETE",
        params={"reason": "PostgreSQL 隔离删除验证"},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["deleted_count"] == 1
    with SessionLocal() as db:
        outbox_state = [{
            "store": row.target_store,
            "status": row.status,
            "failure": row.failure_reason,
        } for row in db.scalars(select(MemoryLifecycleOutbox).where(
            MemoryLifecycleOutbox.task_id == body["task_id"]
        )).all()]
    assert body["verification_passed"] is True, {"body": body, "outbox": outbox_state}

    verification = client.get(
        f"/api/v1/memory/lifecycle/tasks/{body['task_id']}/delete-verification",
        headers=headers,
    )
    assert verification.status_code == 200
    assert verification.json()["delete_no_recall"] is True
    assert {item["target_store"] for item in verification.json()["stores"]} == {
        "POSTGRESQL", "REDIS", "VECTOR", "OBJECT"
    }

    with SessionLocal() as db:
        record = db.get(MemoryRecord, "MEM-PG-41-DELETE")
        assert record.status == MemoryStatus.DELETED
        assert record.content == "[DELETED]"
        assert db.scalar(select(MemoryDeleteVerification).where(
            MemoryDeleteVerification.task_id == body["task_id"],
            MemoryDeleteVerification.target_store == "POSTGRESQL",
        )).status == "VERIFIED"
