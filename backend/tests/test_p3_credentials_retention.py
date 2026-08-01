from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.database import SessionLocal
from app.governance.contracts import CredentialStatus
from app.governance.models import CredentialReference, CredentialUsageAudit, GovernanceAuditEvent
from app.governance.retention import LegalHoldService, RetentionPolicyService
from app.governance.secrets import (
    CredentialReferenceService,
    EnvironmentSecretProvider,
    SecretProviderRegistry,
    SecretResolutionError,
)
from app.memory.deletion import MemoryDeletionService
from app.memory.semantic import SemanticMemoryService
from app.models.auth import User
from app.platform.identity import IdentityContextFactory


def _admin(db):
    user = db.scalar(select(User).where(User.username == "analyst"))
    assert user
    return IdentityContextFactory.from_user(user, request_id="trace-p3-admin")


def _memory(db, identity, suffix: str):
    service = SemanticMemoryService(db, identity)
    candidate = service.propose(
        key="answer_style",
        value=f"style-{suffix}",
        scenario_id="charging_ops",
        source_type="USER_STATEMENT",
        source_id=None,
        explicitly_confirmed=True,
        idempotency_key=f"p3-memory-{suffix}",
        write_reason="P3 governance acceptance",
    )
    return service.confirm(candidate.candidate_id)


def test_credential_reference_rotation_disable_and_audit(client, monkeypatch) -> None:
    monkeypatch.setenv("P3_TEST_SECRET_V1", "ephemeral-value-v1")
    monkeypatch.setenv("P3_TEST_SECRET_V2", "ephemeral-value-v2")
    registry = SecretProviderRegistry((EnvironmentSecretProvider({"P3_TEST_SECRET_V1", "P3_TEST_SECRET_V2"}),))
    with SessionLocal() as db:
        identity = _admin(db)
        service = CredentialReferenceService(db, identity, providers=registry)
        reference = service.create(
            reference_name="sqlbot-evaluation",
            provider="ENV",
            secret_identifier="P3_TEST_SECRET_V1",
            purpose="isolated SQLBot evaluation",
            scenario_id="charging_ops",
            environment="test",
            allowed_actions=["sqlbot.authenticate"],
            metadata={"owner": "platform-admin"},
        )
        resolved = service.resolve(reference.credential_ref_id, action="sqlbot.authenticate", trace_id="trace-credential-v1")
        assert resolved.value == "ephemeral-value-v1"

        replacement = service.rotate(
            reference.credential_ref_id,
            secret_identifier="P3_TEST_SECRET_V2",
            metadata={"owner": "platform-admin", "rotation": 2},
        )
        assert replacement.version == 2
        assert replacement.rotated_from_id == reference.credential_ref_id
        assert db.get(CredentialReference, reference.credential_ref_id).status == "SUPERSEDED"
        service.set_status(replacement.credential_ref_id, status=CredentialStatus.DISABLED)
        with pytest.raises(SecretResolutionError) as disabled:
            service.resolve(replacement.credential_ref_id, action="sqlbot.authenticate", trace_id="trace-disabled")
        assert disabled.value.code == "CREDENTIAL_REFERENCE_DISABLED"

        usage = list(db.scalars(select(CredentialUsageAudit)).all())
        assert {row.outcome for row in usage} == {"SUCCESS", "FAILED"}
        persisted = json.dumps([
            {
                "identifier": row.secret_identifier,
                "metadata": row.metadata_json,
            }
            for row in db.scalars(select(CredentialReference)).all()
        ])
        audit_payload = "\n".join(db.scalars(select(GovernanceAuditEvent.detail_json)).all())
        assert "ephemeral-value-v1" not in persisted + audit_payload
        assert "ephemeral-value-v2" not in persisted + audit_payload


def test_credential_reference_rejects_sensitive_metadata_and_missing_provider_value(client) -> None:
    registry = SecretProviderRegistry((EnvironmentSecretProvider({"P3_MISSING_SECRET"}),))
    with SessionLocal() as db:
        service = CredentialReferenceService(db, _admin(db), providers=registry)
        with pytest.raises(SecretResolutionError) as metadata_error:
            service.create(
                reference_name="invalid-sensitive-metadata",
                provider="ENV",
                secret_identifier="P3_MISSING_SECRET",
                purpose="negative test",
                scenario_id=None,
                environment="test",
                allowed_actions=["test"],
                metadata={"password": "must-not-persist"},
            )
        assert metadata_error.value.code == "PLAINTEXT_SECRET_METADATA_REJECTED"

        reference = service.create(
            reference_name="missing-provider-value",
            provider="ENV",
            secret_identifier="P3_MISSING_SECRET",
            purpose="negative test",
            scenario_id=None,
            environment="test",
            allowed_actions=["test"],
            metadata={},
        )
        with pytest.raises(SecretResolutionError) as missing:
            service.resolve(reference.credential_ref_id, action="test", trace_id="trace-missing")
        assert missing.value.code == "SECRET_PROVIDER_VALUE_MISSING"


def test_legal_hold_and_retention_apply_strictest_deletion_rule(client) -> None:
    with SessionLocal() as db:
        identity = _admin(db)
        first = _memory(db, identity, "hold")
        hold = LegalHoldService(db, identity).create(
            resource_type="memory",
            resource_id=first.memory_id,
            user_id=identity.subject_id,
            memory_type=first.memory_type,
            reason_code="P3_ACCEPTANCE",
            reason="governance acceptance hold",
        )
        blocked = MemoryDeletionService(db, identity).delete_one(first.memory_id, reason="blocked by hold")
        assert blocked.deleted_count == 0
        assert blocked.legal_hold_count == 1
        assert db.get(type(first), first.memory_id).deleted_at is None

        LegalHoldService(db, identity).release(hold.legal_hold_id, reason="acceptance completed")
        deleted = MemoryDeletionService(db, identity).delete_one(first.memory_id, reason="hold released")
        assert deleted.deleted_count == 1

        second = _memory(db, identity, "retention")
        retention = RetentionPolicyService(db, identity).create(
            policy_code="p3-memory-retention",
            resource_type="memory",
            resource_id=second.memory_id,
            user_id=identity.subject_id,
            memory_type=second.memory_type,
            retention_days=365,
            archive_after_days=180,
            deletion_mode="ANONYMIZE",
        )
        RetentionPolicyService(db, identity).approve_and_activate(retention.retention_policy_id)
        retained = MemoryDeletionService(db, identity).delete_one(second.memory_id, reason="retention conflict")
        assert retained.deleted_count == 0
        assert retained.retention_blocked_count == 1
        assert db.get(type(second), second.memory_id).deleted_at is None


def test_business_user_cannot_manage_legal_hold(client, login) -> None:
    response = client.post(
        "/api/v1/governance/legal-holds",
        headers=login(username="executive", password="AlphaExec!2026"),
        json={
            "resource_type": "memory",
            "resource_id": "MEM-NOT-RELEVANT",
            "reason_code": "UNAUTHORIZED",
            "reason": "must be denied",
        },
    )
    assert response.status_code == 403
