"""Fail closed before any SQLBot external model request when authorization is absent."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app.core.database import SessionLocal
from app.governance.models import CredentialReference
from app.preproduction.models import PreproductionAcceptanceRecord


RUN_ID = "P4-SQLBOT-EXTERNAL-GATE-20260801"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--authorized-model-credential-ref",
        help="Explicitly authorized external model credential reference; omit to enforce the zero-request gate.",
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        authorized = None
        if args.authorized_model_credential_ref:
            authorized = db.scalar(select(CredentialReference).where(
                CredentialReference.credential_ref_id == args.authorized_model_credential_ref,
                CredentialReference.provider == "VAULT_KV_V2",
                CredentialReference.status == "ACTIVE",
                CredentialReference.environment == "preproduction",
            ))
        if authorized is not None:
            raise SystemExit(
                "An authorized model credential was supplied. Run the reviewed 10/30/20 commands explicitly; "
                "this gate never initiates external network calls."
            )

        now = datetime.now(UTC)
        report = {
            "evidence_type": "p4_sqlbot_secure_external_reevaluation_gate",
            "run_id": RUN_ID,
            "evaluated_at": now.isoformat(),
            "status": "CONDITIONAL",
            "reason": "No explicitly authorized external model CredentialReference was supplied.",
            "request_gate": "EXITED_BEFORE_NETWORK_REQUEST",
            "actual_external_requests": 0,
            "smoke_10": {"status": "NOT_EXECUTED", "requested": 0, "successful": 0},
            "representative_golden_30": {"status": "NOT_EXECUTED", "requested": 0, "successful": 0},
            "shadow_20": {"status": "NOT_EXECUTED", "requested": 0, "successful": 0},
            "sql_generation_rate": None,
            "guard_pass_rate": None,
            "security_violations": 0,
            "field_hallucinations": None,
            "table_hallucinations": None,
            "timeouts": 0,
            "provider_errors": 0,
            "p50_latency_ms": None,
            "p95_latency_ms": None,
            "token_usage": None,
            "cost": None,
            "source_binding_version": "P4-SIMULATED-SOURCE-BINDING-v1",
            "query_engine_mode": "SHADOW",
            "sqlbot_engine_enabled": False,
            "sqlbot_runtime_verified": False,
            "sqlbot_canary_eligible": False,
            "credential_values_exposed": False,
            "model_response_reused": False,
        }
        serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
        evidence_hash = hashlib.sha256(serialized.encode()).hexdigest()
        existing = db.scalar(select(PreproductionAcceptanceRecord).where(
            PreproductionAcceptanceRecord.run_id == RUN_ID,
            PreproductionAcceptanceRecord.category == "SQLBOT_EXTERNAL",
        ))
        if existing is None:
            db.add(PreproductionAcceptanceRecord(
                acceptance_id="ACC-P4-SQLBOT-EXTERNAL-GATE",
                run_id=RUN_ID,
                category="SQLBOT_EXTERNAL",
                status="CONDITIONAL",
                environment="preproduction",
                metrics_json=json.dumps(report, sort_keys=True),
                evidence_hash=evidence_hash,
                data_classification="simulated",
                started_at=now,
                finished_at=now,
                created_by="system:p4-sqlbot-gate",
            ))
            db.commit()
    print(json.dumps({
        "status": "CONDITIONAL",
        "actual_external_requests": 0,
        "request_gate": "EXITED_BEFORE_NETWORK_REQUEST",
        "output": str(args.output),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
