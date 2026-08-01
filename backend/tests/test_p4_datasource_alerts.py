from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy import select

from app.bootstrap import bootstrap_demo_users
from app.core.config import Settings
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.governance.contracts import SecretValue
from app.governance.models import CredentialReference, SecurityAlert
from app.governance.secrets import CredentialReferenceService
from app.models.auth import User
from app.platform.identity import IdentityContextFactory
from app.preproduction.alerts import SignedWebhookAlertAdapter
from app.preproduction.datasource import DataSourceGovernanceError, DataSourceGovernanceService


def admin_identity(db):
    analyst = db.scalar(select(User).where(User.username == "analyst"))
    return IdentityContextFactory.from_user(analyst, request_id="P4-UNIT")


def add_reference(db, identity, *, ref_id="CRED-P4-TEST", name="preprod-datasource-password", actions=None):
    row = CredentialReference(
        credential_ref_id=ref_id, reference_name=name, provider="VAULT_KV_V2",
        secret_identifier="preprod-kv/chatbi/datasource#password@1",
        purpose="unit test reference", tenant_id=identity.tenant_id,
        workspace_id=identity.workspace_id, environment="test", status="ACTIVE", version=1,
        allowed_actions_json=json.dumps(actions or ["datasource.connect", "datasource.discover", "datasource.profile"]),
        metadata_json="{}", created_by=identity.subject_id,
    )
    db.add(row)
    db.commit()
    return row


def test_datasource_requires_evidence_and_approval_before_activation(client, monkeypatch) -> None:
    bootstrap_demo_users()
    monkeypatch.setattr(get_settings(), "vault_enabled", True)
    with SessionLocal() as db:
        identity = admin_identity(db)
        reference = add_reference(db, identity)
        service = DataSourceGovernanceService(db, identity)
        source = service.create(
            display_name="P4 unit source", source_type="postgresql", host="db", port=5432,
            database_name="simulated", username="readonly", credential_ref_id=reference.credential_ref_id,
            scenario_id="charging_ops",
        )
        with pytest.raises(DataSourceGovernanceError) as exc:
            service.submit(source.source_id)
        assert exc.value.code == "DATASOURCE_EVIDENCE_INCOMPLETE"
        with pytest.raises(DataSourceGovernanceError):
            service.activate(source.source_id)
        source.connection_options_json = json.dumps({
            "connection_test": {"status": "PASS"},
            "schema_discovery": {"status": "PASS"},
            "profile": {"status": "PASS"},
        })
        db.commit()
        assert service.payload(service.submit(source.source_id))["lifecycle_status"] == "REVIEW"
        assert service.payload(service.approve(source.source_id))["lifecycle_status"] == "APPROVED"
        assert service.payload(service.publish(source.source_id))["lifecycle_status"] == "PUBLISHED"
        assert service.payload(service.activate(source.source_id))["lifecycle_status"] == "ACTIVE"
        rotated = service.rotate(
            source.source_id,
            secret_identifier="preprod-kv/chatbi/datasource#password@2",
        )
        rotated.connection_options_json = source.connection_options_json
        db.commit()
        service.submit(rotated.source_id)
        service.approve(rotated.source_id)
        service.publish(rotated.source_id)
        service.activate(rotated.source_id)
        rolled_back = service.rollback(rotated.source_id, target_source_id=source.source_id)
        rollback_governance = service._governance(rolled_back)
        rollback_credential = db.get(CredentialReference, rollback_governance.credential_ref_id)
        assert service.payload(rolled_back)["lifecycle_status"] == "ACTIVE"
        assert rollback_credential.status == "ACTIVE"
        assert rollback_credential.secret_identifier.endswith("@1")
        assert rollback_credential.credential_ref_id != reference.credential_ref_id
        assert service.payload(service.disable(rolled_back.source_id))["lifecycle_status"] == "DISABLED"
        assert service.payload(service.archive(rolled_back.source_id))["lifecycle_status"] == "ARCHIVED"
        service._governance(source).tenant_id = "different-tenant"
        db.commit()
        with pytest.raises(DataSourceGovernanceError) as exc:
            service._owned(source.source_id)
        assert exc.value.code == "DATASOURCE_NOT_FOUND"


def test_external_alert_is_signed_redacted_and_idempotent(client, monkeypatch) -> None:
    bootstrap_demo_users()
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        captured["signature"] = request.headers["X-P4-Signature"]
        return httpx.Response(200, json={"accepted": True})

    with SessionLocal() as db:
        identity = admin_identity(db)
        reference = add_reference(
            db, identity, ref_id="CRED-P4-WEBHOOK", name="preprod-webhook-signing", actions=["alert.sign"],
        )
        alert = SecurityAlert(
            alert_id="ALERT-P4-UNIT", tenant_id=identity.tenant_id,
            workspace_id=identity.workspace_id, rule_code="CROSS_TENANT_ATTEMPT",
            correlation_key="must-not-leave-platform", severity="high", status="OPEN",
            event_count=1, summary="must-not-leave-platform", trace_id="trace-sensitive",
        )
        db.add(alert)
        db.commit()
        monkeypatch.setattr(CredentialReferenceService, "resolve", lambda *args, **kwargs: SecretValue(
            value="unit-signing-key", credential_ref_id=reference.credential_ref_id, version=1,
        ))
        settings = Settings(
            app_env="test", external_alert_enabled=True,
            external_alert_webhook_url="http://alert-receiver:8090/webhook",
            external_alert_signing_reference_name="preprod-webhook-signing",
        )
        adapter = SignedWebhookAlertAdapter(
            db, identity, settings=settings,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        first = adapter.deliver(alert.alert_id, idempotency_key="P4-IDEMPOTENCY-UNIT")
        replay = adapter.deliver(alert.alert_id, idempotency_key="P4-IDEMPOTENCY-UNIT")
        assert first["status"] == "DELIVERED"
        assert replay["idempotent_replay"] is True
        assert captured["signature"].startswith("sha256=")
        serialized = json.dumps(captured["body"])
        assert "must-not-leave-platform" not in serialized
        assert "unit-signing-key" not in serialized
        assert set(captured["body"]) == {
            "schema_version", "alert_id", "rule_code", "severity", "status",
            "environment", "data_classification", "trace_hash",
        }
