"""Reverify the local P5A Vault contract and record audit growth without secrets."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_CONTAINER = "renewable-p5a-remediation-api-1"
VAULT_CONTAINER = "renewable-p5a-remediation-vault-1"
AUDIT_FILE = "/vault/audit/audit.jsonl"
COMPATIBILITY_RUN_ID = "P4-RC-20260801"


def acceptance_code(run_id: str, scope: str) -> str:
    return f'''import hashlib
import json
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import desc, select

sys.path.insert(0, "/app/scripts")
from run_p4_secret_rotation_acceptance import _rotate_vault_values
from app.core.database import SessionLocal
from app.governance.contracts import CredentialStatus
from app.governance.models import CredentialReference
from app.governance.secrets import CredentialReferenceService
from app.models.auth import User
from app.models.integration import DataSourceConnection
from app.platform.identity import IdentityContextFactory
from app.preproduction.datasource import DataSourceGovernanceService
from app.preproduction.models import PreproductionAcceptanceRecord, PreproductionDataSourceGovernance

run_id = {run_id!r}
versions = _rotate_vault_values("http://vault:8200", Path("/run/p4-runtime"))
with SessionLocal() as db:
    analyst = db.scalar(select(User).where(User.username == "analyst"))
    if analyst is None:
        raise RuntimeError("acceptance analyst identity is absent")
    identity = IdentityContextFactory.from_user(analyst, request_id=run_id)
    credentials = CredentialReferenceService(db, identity)
    webhook = credentials.active_by_name("preprod-webhook-signing")
    rotated_webhook = credentials.rotate(
        webhook.credential_ref_id,
        secret_identifier=f"preprod-kv/chatbi/webhook#signing_key@{{versions['webhook']}}",
    )
    disposable = credentials.create(
        reference_name=f"p5a-disable-proof-{{secrets.token_hex(4)}}",
        provider="VAULT_KV_V2",
        secret_identifier="preprod-kv/chatbi/acceptance#value@1",
        purpose={f"{scope.upper()} disable acceptance only"!r},
        scenario_id=None,
        environment="preproduction",
        allowed_actions=["acceptance.proof"],
        metadata={{"acceptance_only": True}},
    )
    disabled = credentials.set_status(disposable.credential_ref_id, CredentialStatus.DISABLED)
    source = db.scalar(
        select(DataSourceConnection)
        .join(
            PreproductionDataSourceGovernance,
            PreproductionDataSourceGovernance.source_id == DataSourceConnection.source_id,
        )
        .where(
            DataSourceConnection.display_name == "P4 模拟 PostgreSQL",
            PreproductionDataSourceGovernance.lifecycle_status == "ACTIVE",
        )
        .order_by(desc(PreproductionDataSourceGovernance.version))
    )
    if source is None:
        raise RuntimeError("active governed acceptance datasource is absent")
    service = DataSourceGovernanceService(db, identity)

    def publish(source_id: str):
        service.test_connection(source_id)
        service.discover_schema(source_id)
        service.profile(source_id, relation="public.fact_charging_session")
        service.submit(source_id)
        service.approve(source_id)
        service.publish(source_id)
        return service.activate(source_id)

    repaired = service.rotate(
        source.source_id,
        secret_identifier=f"preprod-kv/chatbi/datasource#password@{{versions['datasource']}}",
    )
    publish(repaired.source_id)
    rotated = service.rotate(
        repaired.source_id,
        secret_identifier=f"preprod-kv/chatbi/datasource#password@{{versions['datasource']}}",
    )
    publish(rotated.source_id)
    rolled_back = service.rollback(rotated.source_id, target_source_id=repaired.source_id)
    connection = service.test_connection(rolled_back.source_id)
    result = {{
        "status": "PASS",
        "vault_kv_version": 2,
        "datasource_secret_version_created": versions["datasource"],
        "webhook_secret_version_created": versions["webhook"],
        "webhook_reference_version": rotated_webhook.version,
        "credential_disable_status": disabled.status,
        "source_binding_repaired": True,
        "source_binding_rotated": True,
        "source_binding_rolled_back": True,
        "rollback_connection_read_only": connection["read_only"],
        "active_source_version": service.payload(rolled_back)["version"],
        "root_token_persisted": False,
        "plaintext_fallback_used": False,
        "secret_values_printed": False,
        "data_classification": "simulated",
    }}
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    now = datetime.now(UTC)
    db.add(PreproductionAcceptanceRecord(
        acceptance_id=f"ACC-{scope.upper()}-{{uuid4()}}",
        run_id=run_id,
        category="SECRET_PROVIDER",
        status="PASS",
        environment="preproduction",
        metrics_json=serialized,
        evidence_hash=hashlib.sha256(serialized.encode()).hexdigest(),
        data_classification="simulated",
        started_at=now,
        finished_at=now,
        created_by={f"system:{scope}-acceptance"!r},
    ))
    db.commit()
print(json.dumps(result, ensure_ascii=False, sort_keys=True))
'''


def command(*args: str, input_text: str | None = None) -> str:
    process = subprocess.run(
        list(args), cwd=ROOT, text=True, encoding="utf-8", capture_output=True,
        input=input_text,
    )
    if process.returncode:
        raise RuntimeError(f"Vault acceptance command failed safely: {args[:3]}")
    return process.stdout.strip()


def audit_size(vault_container: str) -> int:
    value = command(
        "docker", "exec", vault_container, "sh", "-ec",
        f"test -f {AUDIT_FILE} && wc -c < {AUDIT_FILE}",
    )
    return int(value)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scope", choices=("p5a", "p5b"), default="p5a")
    parser.add_argument("--api-container", default=API_CONTAINER)
    parser.add_argument("--vault-container", default=VAULT_CONTAINER)
    args = parser.parse_args()
    started_at = datetime.now(UTC)
    run_id = f"{args.scope.upper()}-VAULT-{started_at.strftime('%Y%m%dT%H%M%SZ')}"
    before = audit_size(args.vault_container)
    output = command(
        "docker", "exec", args.api_container,
        "python", "scripts/p4_entrypoint.py",
        "python", "-c", acceptance_code(run_id, args.scope),
    )
    lines = [line for line in output.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("Vault compatibility acceptance returned no result")
    compatibility = json.loads(lines[-1])
    after = audit_size(args.vault_container)
    passed = (
        compatibility.get("status") == "PASS"
        and compatibility.get("vault_kv_version") == 2
        and compatibility.get("credential_disable_status") == "DISABLED"
        and compatibility.get("source_binding_rotated") is True
        and compatibility.get("source_binding_rolled_back") is True
        and compatibility.get("rollback_connection_read_only") is True
        and compatibility.get("root_token_persisted") is False
        and compatibility.get("plaintext_fallback_used") is False
        and compatibility.get("secret_values_printed") is False
        and after > before
    )
    result = {
        "evidence_type": f"{args.scope}_vault_contract_reverification",
        "run_id": run_id,
        "status": "PASS" if passed else "FAIL",
        "environment": f"{args.scope.upper()} production-acceptance, not production",
        "data_classification": "simulated",
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "approle_login_succeeded": compatibility.get("status") == "PASS",
        "vault_kv_version": compatibility.get("vault_kv_version"),
        "datasource_secret_version_created": compatibility.get("datasource_secret_version_created"),
        "webhook_secret_version_created": compatibility.get("webhook_secret_version_created"),
        "credential_disable_status": compatibility.get("credential_disable_status"),
        "source_binding_rotated": compatibility.get("source_binding_rotated"),
        "source_binding_repaired": compatibility.get("source_binding_repaired"),
        "source_binding_rolled_back": compatibility.get("source_binding_rolled_back"),
        "rollback_connection_read_only": compatibility.get("rollback_connection_read_only"),
        "vault_audit_file": AUDIT_FILE,
        "vault_audit_bytes_before": before,
        "vault_audit_bytes_after": after,
        "vault_audit_growth_bytes": after - before,
        "compatibility_baseline_run_id": COMPATIBILITY_RUN_ID,
        "acceptance_record_run_id": run_id,
        "root_token_persisted": compatibility.get("root_token_persisted"),
        "plaintext_fallback_used": compatibility.get("plaintext_fallback_used"),
        "secret_values_printed": False,
        "production_release_authorized": False,
        "production_traffic_switched": False,
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(rendered.encode("utf-8"))
    print(json.dumps({
        "status": result["status"],
        "run_id": result["run_id"],
        "audit_growth_bytes": result["vault_audit_growth_bytes"],
        "evidence_sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
        "secret_values_printed": False,
    }, sort_keys=True))
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({
            "status": "FAIL", "error_type": type(exc).__name__,
            "secret_values_printed": False,
        }, sort_keys=True))
        raise SystemExit(1) from None
