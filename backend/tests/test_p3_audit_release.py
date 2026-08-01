from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.database import SessionLocal
from app.governance.audit import GovernanceAuditQuery, record_governance_event
from app.governance.models import GovernanceAuditEvent, SecurityAlert
from app.governance.policy import PolicyGovernanceError, PolicyGovernanceService
from app.governance.release import ReleaseGovernanceError, ReleaseRegistry
from app.memory.procedural import ProcedureRegistry, ProcedureRegistryError, ProcedureSpec
from app.models.auth import User
from app.platform.identity import IdentityContextFactory


def _identity(db):
    user = db.scalar(select(User).where(User.username == "analyst"))
    assert user
    return IdentityContextFactory.from_user(user, request_id="trace-p3-governance")


def test_governance_audit_redaction_filter_export_alert_and_immutability(client) -> None:
    with SessionLocal() as db:
        identity = _identity(db)
        for ordinal in range(3):
            record_governance_event(
                db,
                identity,
                action="authorization.denied",
                resource_type="dataset",
                resource_id="restricted-dataset",
                result="DENIED",
                trace_id=f"trace-denial-{ordinal}",
                detail={"password": "ephemeral-sensitive-value", "reason": "test"},
                commit=True,
            )
        alert = db.scalar(select(SecurityAlert).where(SecurityAlert.rule_code == "CONSECUTIVE_AUTH_DENIAL"))
        assert alert and alert.status == "OPEN" and alert.event_count == 3

        rows, total = GovernanceAuditQuery(db, identity).search(
            action="authorization.denied", result="DENIED", page=1, page_size=2
        )
        assert total == 3 and len(rows) == 2
        assert all("ephemeral-sensitive-value" not in row.detail_json for row in rows)
        exported = GovernanceAuditQuery(db, identity).export_csv(action="authorization.denied", result="DENIED")
        assert "trace_id" in exported and "restricted-dataset" in exported

        event = rows[0]
        event.result = "SUCCESS"
        with pytest.raises(RuntimeError, match="immutable"):
            db.commit()
        db.rollback()


def test_policy_and_procedure_cannot_activate_without_review(client) -> None:
    with SessionLocal() as db:
        identity = _identity(db)
        policy = PolicyGovernanceService(db, identity).create(
            policy_code="p3-unreviewed-policy",
            effect="ALLOW",
            actions=["metric.query"],
            resource_types=["metric"],
            conditions={"environments": ["test"]},
        )
        with pytest.raises(PolicyGovernanceError) as policy_error:
            PolicyGovernanceService(db, identity).activate(policy.policy_id)
        assert policy_error.value.code == "POLICY_NOT_APPROVED"

        procedure = ProcedureRegistry(db, identity).register(ProcedureSpec(
            procedure_code="p3_unreviewed_procedure",
            version="1.0.0",
            scenario_id="charging_ops",
            owner_subject_id=identity.subject_id,
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            steps=({"code": "step-1"},),
            branches=(),
            validations=({"code": "validation-1"},),
            failure_policy={"mode": "fail_closed"},
            test_manifest={"passed": True, "case_count": 1},
        ))
        with pytest.raises(ProcedureRegistryError) as procedure_error:
            ProcedureRegistry(db, identity).activate(procedure.procedure_id)
        assert procedure_error.value.code == "PROCEDURE_NOT_APPROVED"


def test_release_state_machine_production_block_and_history_preserving_rollback(client) -> None:
    with SessionLocal() as db:
        registry = ReleaseRegistry(db, _identity(db))
        v1 = registry.create(
            object_type="SEMANTIC_MODEL",
            object_id="charging-ops-semantic",
            version="1.0.0",
            environment="staging",
            artifact_hash="1" * 64,
            change_summary="P3 staging baseline",
        )
        with pytest.raises(ReleaseGovernanceError) as unapproved:
            registry.activate(v1.release_id)
        assert unapproved.value.code == "RELEASE_NOT_APPROVED"
        registry.submit_review(v1.release_id)
        registry.approve(v1.release_id)
        registry.activate(v1.release_id)

        v2 = registry.create(
            object_type="SEMANTIC_MODEL",
            object_id="charging-ops-semantic",
            version="1.1.0",
            environment="staging",
            artifact_hash="2" * 64,
            change_summary="P3 candidate",
        )
        registry.submit_review(v2.release_id)
        registry.approve(v2.release_id)
        registry.activate(v2.release_id)
        assert db.get(type(v1), v1.release_id).status == "SUPERSEDED"

        rollback = registry.rollback(v2.release_id, target_release_id=v1.release_id)
        assert rollback.status == "ACTIVE"
        assert rollback.rollback_of_release_id == v2.release_id
        assert db.get(type(v1), v1.release_id) is not None
        assert db.get(type(v2), v2.release_id).status == "ROLLED_BACK"

        production = registry.create(
            object_type="POLICY_BUNDLE",
            object_id="p3-policy-bundle",
            version="1.0.0",
            environment="production",
            artifact_hash="3" * 64,
            change_summary="must remain blocked",
        )
        registry.submit_review(production.release_id)
        registry.approve(production.release_id)
        with pytest.raises(ReleaseGovernanceError) as blocked:
            registry.activate(production.release_id)
        assert blocked.value.code == "PRODUCTION_RELEASE_DISABLED"

        audit_actions = set(db.scalars(select(GovernanceAuditEvent.action)).all())
        assert {"release.activated", "release.rolled_back", "release.production_blocked"} <= audit_actions
