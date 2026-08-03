from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.database import SessionLocal
from app.production_acceptance.models import ProductionGateHistory


def _decision(status: str, *, evidence: bool = True) -> dict:
    payload = {
        "status": status,
        "expires_at": (datetime.now(UTC) + timedelta(days=14)).isoformat(),
        "reason": "P5 machine-verifiable acceptance evidence update",
        "evidence": [],
    }
    if evidence:
        payload["evidence"] = [{
            "evidence_type": "test_result",
            "uri": "docs/platformization/p5/evidence/rag_keyword_regression.json",
            "sha256": "a" * 64,
            "observed_at": datetime.now(UTC).isoformat(),
            "summary": "Keyword-only permission, injection and citation regression passed.",
        }]
    return payload


def test_registry_snapshot_is_database_backed_and_no_go_by_default(client, login) -> None:
    response = client.get("/api/v1/production-acceptance/snapshot", headers=login())
    assert response.status_code == 200
    body = response.json()
    assert len(body["gates"]) == 28
    assert body["summary"]["go_no_go_recommendation"] == "NO_GO"
    assert body["summary"]["production_acceptance_ready"] is False
    assert body["runtime_contract"] == {
        "query_engine_mode": "SHADOW",
        "sqlbot_release_scope": "NOT_INCLUDED_IN_V4_RELEASE",
        "sqlbot_engine_enabled": False,
        "sqlbot_image_in_bom": False,
        "sqlbot_canary_eligible": False,
        "sqlbot_external_evaluation": "DEFERRED",
        "rag_runtime_mode": "KEYWORD_ONLY",
        "rag_vector_released": False,
        "production_release_authorized": False,
        "production_traffic_switched": False,
    }
    gates = {item["gate_code"]: item for item in body["gates"]}
    assert set(gates) == {
        "REMOTE_PUSH", "DOCKER_RUNTIME", "POSTGRES_CANONICAL_REGRESSION", "FRONTEND_E2E",
        "IMAGE_SECURITY", "KEYCLOAK_SECURITY", "VAULT_SECURITY", "SQLBOT_IMAGE_SECURITY",
        "CAPACITY_SOAK", "BACKUP_RECOVERY", "ENTERPRISE_IDP", "PRODUCTION_SECRET_MANAGER",
        "SECRET_MANAGER", "SQLBOT_EXTERNAL_REVIEW", "SQLBOT_EXTERNAL_RUNTIME", "RAG_MODE",
        "PRODUCTION_DATA_APPROVAL", "PRODUCTION_DATA", "PRODUCTION_CAPACITY", "BACKUP_RESTORE",
        "MONITORING_ALERTING", "ENTERPRISE_ALERT", "CHANGE_WINDOW", "ROLLBACK_DRILL",
        "RISK_ACCEPTANCE", "BUSINESS_APPROVAL", "SECURITY_APPROVAL", "OPERATIONS_APPROVAL",
    }
    assert sum(not item["external_condition"] for item in body["gates"]) == 13
    assert sum(item["external_condition"] for item in body["gates"]) == 15
    assert gates["REMOTE_PUSH"]["status"] == "BLOCKED"
    assert gates["ENTERPRISE_IDP"]["recorded_status"] == "OPEN"
    assert gates["ENTERPRISE_IDP"]["display_status"] == "CONDITIONAL"
    assert gates["ENTERPRISE_IDP"]["evidence"] == []
    assert gates["IMAGE_SECURITY"]["status"] == "BLOCKED"
    assert gates["SQLBOT_IMAGE_SECURITY"]["recorded_status"] == "BLOCKED"
    assert gates["SQLBOT_IMAGE_SECURITY"]["applicable_to_release"] is False
    assert gates["SQLBOT_IMAGE_SECURITY"]["blocking_scope"] == "future_sqlbot_release"
    assert gates["SQLBOT_EXTERNAL_RUNTIME"]["release_disposition"] == "DEFERRED"
    assert "SQLBOT_IMAGE_SECURITY" not in body["summary"]["unresolved_blockers"]
    assert body["summary"]["not_applicable_to_v4"] == [
        "SQLBOT_EXTERNAL_REVIEW", "SQLBOT_EXTERNAL_RUNTIME", "SQLBOT_IMAGE_SECURITY",
    ]
    assert gates["RAG_MODE"]["status"] == "PASSED"
    assert gates["RAG_MODE"]["evidence"][0]["sha256"] == "a59c871188aba4216a82281790a7bb1e3064ed0dc28f83e11fff144e35eccd8e"
    assert all(item["owner"] and item["expires_at"] and item["review_requirement"] for item in body["gates"])


def test_business_user_can_view_but_cannot_change_gate(client, login) -> None:
    headers = login(username="executive", password="AlphaExec!2026")
    assert client.get("/api/v1/production-acceptance/snapshot", headers=headers).status_code == 200
    denied = client.post(
        "/api/v1/production-acceptance/gates/BACKUP_RESTORE/decision",
        headers=headers,
        json=_decision("PASSED"),
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "RBAC_PERMISSION_DENIED"


def test_pass_requires_evidence_and_records_immutable_history(client, login) -> None:
    headers = login()
    rejected = client.post(
        "/api/v1/production-acceptance/gates/BACKUP_RESTORE/decision",
        headers=headers,
        json=_decision("PASSED", evidence=False),
    )
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "PRODUCTION_GATE_EVIDENCE_REQUIRED"

    accepted = client.post(
        "/api/v1/production-acceptance/gates/BACKUP_RESTORE/decision",
        headers=headers,
        json=_decision("PASSED"),
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "PASSED"
    assert accepted.json()["evidence_hash"]
    assert accepted.json()["version"] == 2

    history = client.get(
        "/api/v1/production-acceptance/gates/BACKUP_RESTORE/history",
        headers=headers,
    )
    assert history.status_code == 200
    assert len(history.json()["history"]) == 1
    assert history.json()["history"][0]["previous_status"] == "OPEN"

    with SessionLocal() as db:
        row = db.scalar(select(ProductionGateHistory))
        assert row is not None
        row.reason = "tamper"
        with pytest.raises(RuntimeError, match="immutable"):
            db.commit()


def test_waiver_cannot_be_fabricated_without_formal_approval(client, login) -> None:
    headers = login()
    payload = _decision("WAIVED")
    payload.update({
        "waiver_approved_by": "TBD",
        "waiver_basis": "temporary exception",
        "waiver_evidence_hash": "b" * 64,
    })
    rejected = client.post(
        "/api/v1/production-acceptance/gates/IMAGE_SECURITY/decision",
        headers=headers,
        json=payload,
    )
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "PRODUCTION_GATE_WAIVER_APPROVER_REQUIRED"


def test_gate_scope_cannot_be_selected_from_request_body(client, login) -> None:
    payload = _decision("IN_PROGRESS", evidence=False)
    payload["tenant_id"] = "another-tenant"
    response = client.post(
        "/api/v1/production-acceptance/gates/RAG_MODE/decision",
        headers=login(),
        json=payload,
    )
    assert response.status_code == 422
