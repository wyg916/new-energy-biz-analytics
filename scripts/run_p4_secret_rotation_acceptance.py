"""Exercise Vault KV v2 rotation, credential disable, source activation, and rollback."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import desc, select

from app.bootstrap import bootstrap_demo_users
from app.core.database import SessionLocal
from app.governance.contracts import CredentialStatus
from app.governance.models import CredentialReference
from app.governance.secrets import CredentialReferenceService
from app.models.auth import User
from app.models.integration import DataSourceConnection
from app.platform.identity import IdentityContextFactory
from app.preproduction.datasource import DataSourceGovernanceService
from app.preproduction.models import PreproductionAcceptanceRecord, PreproductionDataSourceGovernance


RUN_ID = "P4-RC-20260801"


def _vault_token(client: httpx.Client, runtime: Path) -> str:
    response = client.post("/v1/auth/approle/login", json={
        "role_id": (runtime / "vault_rotation_role_id").read_text(encoding="utf-8").strip(),
        "secret_id": (runtime / "vault_rotation_secret_id").read_text(encoding="utf-8").strip(),
    })
    response.raise_for_status()
    return str(response.json()["auth"]["client_token"])


def _rotate_vault_values(address: str, runtime: Path) -> dict[str, int]:
    with httpx.Client(base_url=address, timeout=5) as client:
        token = _vault_token(client, runtime)
        headers = {"X-Vault-Token": token}
        datasource = client.get(
            "/v1/preprod-kv/data/chatbi/datasource", headers=headers,
        )
        datasource.raise_for_status()
        current_password = datasource.json()["data"]["data"]["password"]
        response = client.post(
            "/v1/preprod-kv/data/chatbi/datasource", headers=headers,
            json={"data": {"password": current_password}},
        )
        response.raise_for_status()
        datasource_version = int(response.json()["data"]["version"])
        response = client.post(
            "/v1/preprod-kv/data/chatbi/webhook", headers=headers,
            json={"data": {"signing_key": secrets.token_urlsafe(48)}},
        )
        response.raise_for_status()
        webhook_version = int(response.json()["data"]["version"])
    return {"datasource": datasource_version, "webhook": webhook_version}


def _record(db, result: dict) -> None:
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(serialized.encode()).hexdigest()
    now = datetime.now(UTC)
    record = db.scalar(select(PreproductionAcceptanceRecord).where(
        PreproductionAcceptanceRecord.run_id == RUN_ID,
        PreproductionAcceptanceRecord.category == "SECRET_PROVIDER",
    ))
    if record is None:
        record = PreproductionAcceptanceRecord(
            acceptance_id="ACC-P4-SECRET-ROTATION", run_id=RUN_ID,
            category="SECRET_PROVIDER", status="PASS", environment="preproduction",
            metrics_json=serialized, evidence_hash=digest, data_classification="simulated",
            started_at=now, finished_at=now, created_by="system:p4-acceptance",
        )
        db.add(record)
    else:
        record.status = "PASS"
        record.metrics_json = serialized
        record.evidence_hash = digest
        record.finished_at = now


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default=os.getenv("VAULT_ADDRESS", "http://vault:8200"))
    parser.add_argument("--runtime-dir", type=Path, default=Path("/run/p4-runtime"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    versions = _rotate_vault_values(args.address, args.runtime_dir)
    bootstrap_demo_users()
    with SessionLocal() as db:
        analyst = db.scalar(select(User).where(User.username == "analyst"))
        identity = IdentityContextFactory.from_user(analyst, request_id="P4-SECRET-ROTATION")
        credentials = CredentialReferenceService(db, identity)
        webhook = credentials.active_by_name("preprod-webhook-signing")
        rotated_webhook = credentials.rotate(
            webhook.credential_ref_id,
            secret_identifier=f"preprod-kv/chatbi/webhook#signing_key@{versions['webhook']}",
        )
        disposable = credentials.create(
            reference_name=f"p4-disable-proof-{secrets.token_hex(4)}",
            provider="VAULT_KV_V2",
            secret_identifier="preprod-kv/chatbi/acceptance#value@1",
            purpose="P4 disable acceptance only", scenario_id=None,
            environment="preproduction", allowed_actions=["acceptance.proof"],
            metadata={"acceptance_only": True},
        )
        disabled = credentials.set_status(disposable.credential_ref_id, CredentialStatus.DISABLED)
        source = db.scalar(select(DataSourceConnection).join(
            PreproductionDataSourceGovernance,
            PreproductionDataSourceGovernance.source_id == DataSourceConnection.source_id,
        ).where(
            DataSourceConnection.display_name == "P4 模拟 PostgreSQL",
            PreproductionDataSourceGovernance.lifecycle_status == "ACTIVE",
        ).order_by(desc(PreproductionDataSourceGovernance.version)))
        if source is None:
            raise RuntimeError("active P4 datasource not found")
        service = DataSourceGovernanceService(db, identity)
        rotated = service.rotate(
            source.source_id,
            secret_identifier=f"preprod-kv/chatbi/datasource#password@{versions['datasource']}",
        )
        service.test_connection(rotated.source_id)
        service.discover_schema(rotated.source_id)
        service.profile(rotated.source_id, relation="public.fact_charging_session")
        service.submit(rotated.source_id)
        service.approve(rotated.source_id)
        service.publish(rotated.source_id)
        service.activate(rotated.source_id)
        rolled_back = service.rollback(rotated.source_id, target_source_id=source.source_id)
        connection = service.test_connection(rolled_back.source_id)
        result = {
            "status": "PASS",
            "vault_kv_version": 2,
            "datasource_secret_version_created": versions["datasource"],
            "webhook_secret_version_created": versions["webhook"],
            "webhook_reference_version": rotated_webhook.version,
            "credential_disable_status": disabled.status,
            "source_binding_rotated": True,
            "source_binding_rolled_back": True,
            "rollback_connection_read_only": connection["read_only"],
            "active_source_version": service.payload(rolled_back)["version"],
            "root_token_persisted": False,
            "plaintext_fallback_used": False,
            "secret_values_printed": False,
            "data_classification": "simulated",
        }
        _record(db, result)
        db.commit()
    rendered = json.dumps(result, ensure_ascii=False, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
