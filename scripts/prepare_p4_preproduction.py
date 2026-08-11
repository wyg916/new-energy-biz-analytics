"""Seed P4 fixed simulated data and publish governed preproduction bindings."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, date, datetime

from sqlalchemy import func, select, text

from app.bootstrap import bootstrap_demo_users
from app.core.database import SessionLocal
from app.data.seed import SEED as CHARGING_SEED
from app.data.seed import generate_simulated_data
from app.governance.models import (
    CredentialReference, GovernanceBinding, IdentityGroup, IdentityGroupMembership,
    Principal,
)
from app.governance.secrets import CredentialReferenceService
from app.models.auth import User
from app.models.integration import DataIngestionReview, DataIngestionRun, DataSourceConnection
from app.platform.identity import IdentityContextFactory
from app.preproduction.datasource import DataSourceGovernanceService
from app.preproduction.models import PreproductionAcceptanceRecord, PreproductionDataSourceGovernance
from app.scenarios.charging_ops.package_adapter import install_platform_foundation
from app.scenarios.sales_ops.package_adapter import install_sales_ops_foundation
from app.scenarios.sales_ops.seed import DEFAULT_ORDER_COUNT, DEFAULT_SEED, generate_sales_orders
from app.services.data_integration import DataIntegrationService


EXPECTED_REVISION = os.getenv("EXPECTED_DATABASE_REVISION", "p4_0001")
ACCEPTANCE_DATABASE_NAME = os.getenv("ACCEPTANCE_POSTGRES_DB", "renewable_p4")


def published_ingestion(db, analyst: User) -> dict:
    latest = db.scalar(select(DataIngestionRun).where(
        DataIngestionRun.dataset_id == "station-operations",
    ).order_by(DataIngestionRun.started_at.desc(), DataIngestionRun.run_id.desc()))
    review = db.scalar(select(DataIngestionReview).where(DataIngestionReview.run_id == latest.run_id)) if latest else None
    if review and review.workflow_status == "published":
        return {"run_id": latest.run_id, "status": "published", "reused": True}
    service = DataIntegrationService(db, analyst)
    run = service.ingest_dataset("station-operations", date(2026, 1, 1), date(2026, 7, 1), limit=30)
    service.validate_ingestion("station-operations", run["run_id"])
    service.submit_ingestion("station-operations", run["run_id"])
    service.decide_ingestion("station-operations", run["run_id"], "approve")
    result = service.publish_ingestion("station-operations", run["run_id"])
    return {"run_id": run["run_id"], "status": result["workflow_status"], "reused": False}


def credential(service: CredentialReferenceService, name: str, identifier: str, purpose: str, actions: list[str]):
    try:
        return service.active_by_name(name)
    except Exception:
        return service.create(
            reference_name=name, provider="VAULT_KV_V2", secret_identifier=identifier,
            purpose=purpose, scenario_id=None, environment="preproduction",
            allowed_actions=actions, metadata={"data_classification": "simulated", "managed_by": "p4-bootstrap"},
        )


def main() -> None:
    bootstrap_demo_users()
    with SessionLocal() as db:
        revision = db.scalar(text("SELECT version_num FROM alembic_version"))
        if revision != EXPECTED_REVISION:
            raise RuntimeError(f"P4 database must be at {EXPECTED_REVISION}, got {revision}")
        analyst = db.scalar(select(User).where(User.username == "analyst"))
        if analyst is None:
            raise RuntimeError("bootstrap analyst is unavailable")
        identity = IdentityContextFactory.from_user(analyst, request_id="P4-PREPRODUCTION-INIT")
        charging = generate_simulated_data(db, session_count=300_000, seed=CHARGING_SEED)
        charging_platform = install_platform_foundation(db, identity)
        ingestion = published_ingestion(db, analyst)
        sales = generate_sales_orders(db, order_count=DEFAULT_ORDER_COUNT, seed=DEFAULT_SEED)
        sales_platform = install_sales_ops_foundation(db, identity, expected_order_count=DEFAULT_ORDER_COUNT)

        group = db.get(IdentityGroup, "GROUP-P4-ANALYSTS")
        if group is None:
            db.add(IdentityGroup(
                group_id="GROUP-P4-ANALYSTS", tenant_id=identity.tenant_id,
                workspace_id=identity.workspace_id, group_code="analysts",
                display_name="P4 Analysts", status="ACTIVE",
            ))
        principal = db.get(Principal, "PRN-P4-OIDC-ANALYST")
        if principal is None:
            db.add(Principal(
                principal_id="PRN-P4-OIDC-ANALYST", principal_type="USER",
                provider_code="OIDC_PREPROD", external_subject="11111111-1111-4111-8111-111111111111",
                local_user_id=analyst.id, tenant_id=identity.tenant_id,
                organization_id=identity.org_id, workspace_id=identity.workspace_id,
                display_name="P4 Analyst", status="ACTIVE", auth_strength="oidc-pkce",
                attributes_json=json.dumps({
                    "roles": ["analyst_admin"], "required_groups": ["analysts"],
                    "data_scopes": ["workspace:all"],
                }, sort_keys=True),
            ))
        db.flush()
        if db.get(IdentityGroupMembership, "MEMBERSHIP-P4-OIDC-ANALYST") is None:
            db.add(IdentityGroupMembership(
                membership_id="MEMBERSHIP-P4-OIDC-ANALYST", principal_id="PRN-P4-OIDC-ANALYST",
                group_id="GROUP-P4-ANALYSTS", tenant_id=identity.tenant_id,
                workspace_id=identity.workspace_id, status="ACTIVE",
            ))
        bootstrap_principal = db.get(Principal, "PRN-INTEGRATION-KNOWLEDGE-BOOTSTRAP")
        if bootstrap_principal is None:
            db.add(Principal(
                principal_id="PRN-INTEGRATION-KNOWLEDGE-BOOTSTRAP",
                principal_type="SERVICE_USER", provider_code="OIDC_PREPROD",
                external_subject="44444444-4444-4444-8444-444444444444",
                local_user_id=analyst.id, tenant_id=identity.tenant_id,
                organization_id=identity.org_id, workspace_id=identity.workspace_id,
                display_name="Integration / Preproduction Knowledge Bootstrap Principal",
                status="ACTIVE", auth_strength="oidc-pkce",
                attributes_json=json.dumps({
                    "roles": ["analyst_admin"], "required_groups": ["analysts"],
                    "data_scopes": ["workspace:all"],
                    "purpose": "knowledge_baseline_bootstrap",
                }, sort_keys=True),
            ))
            db.flush()
        if db.get(IdentityGroupMembership, "MEMBERSHIP-INTEGRATION-KNOWLEDGE-BOOTSTRAP") is None:
            db.add(IdentityGroupMembership(
                membership_id="MEMBERSHIP-INTEGRATION-KNOWLEDGE-BOOTSTRAP",
                principal_id="PRN-INTEGRATION-KNOWLEDGE-BOOTSTRAP",
                group_id="GROUP-P4-ANALYSTS", tenant_id=identity.tenant_id,
                workspace_id=identity.workspace_id, status="ACTIVE",
            ))
        if db.get(GovernanceBinding, "BIND-P4-OIDC-ANALYST") is None:
            db.add(GovernanceBinding(
                binding_id="BIND-P4-OIDC-ANALYST", tenant_id=identity.tenant_id,
                workspace_id=identity.workspace_id, principal_id="PRN-P4-OIDC-ANALYST",
                role_id="ROLE-ANALYST_ADMIN", resource_type="*", environment="preproduction",
                status="ACTIVE", created_by="system:p4-bootstrap",
            ))
        if db.get(GovernanceBinding, "BIND-INTEGRATION-KNOWLEDGE-BOOTSTRAP") is None:
            db.add(GovernanceBinding(
                binding_id="BIND-INTEGRATION-KNOWLEDGE-BOOTSTRAP",
                tenant_id=identity.tenant_id, workspace_id=identity.workspace_id,
                principal_id="PRN-INTEGRATION-KNOWLEDGE-BOOTSTRAP",
                role_id="ROLE-ANALYST_ADMIN", resource_type="knowledge",
                environment="preproduction", status="ACTIVE",
                created_by="system:integration-knowledge-bootstrap",
            ))
        db.commit()

        secrets_service = CredentialReferenceService(db, identity)
        credential(secrets_service, "preprod-acceptance-proof", "preprod-kv/chatbi/acceptance#value@1", "P4 acceptance proof", ["acceptance.proof"])
        datasource_ref = credential(
            secrets_service, "preprod-datasource-password", "preprod-kv/chatbi/datasource#password@1",
            "P4 simulated datasource", ["datasource.connect", "datasource.discover", "datasource.profile"],
        )
        credential(secrets_service, "preprod-webhook-signing", "preprod-kv/chatbi/webhook#signing_key@1", "P4 local webhook signing", ["alert.sign"])
        credential(secrets_service, "preprod-sqlbot-username", "preprod-kv/chatbi/sqlbot#username@1", "P4 SQLBot runtime username", ["sqlbot.authenticate"])
        credential(secrets_service, "preprod-sqlbot-password", "preprod-kv/chatbi/sqlbot#password@1", "P4 SQLBot runtime password", ["sqlbot.authenticate"])
        credential(
            secrets_service,
            "preprod-knowledge-bootstrap-password",
            "preprod-kv/chatbi/knowledge-bootstrap#password@1",
            "Integration / Preproduction Knowledge Bootstrap Principal",
            ["knowledge.bootstrap.authenticate"],
        )

        data_service = DataSourceGovernanceService(db, identity)
        governed = db.scalar(select(DataSourceConnection).join(
            PreproductionDataSourceGovernance,
            PreproductionDataSourceGovernance.source_id == DataSourceConnection.source_id,
        ).where(
            DataSourceConnection.display_name == "P4 模拟 PostgreSQL",
            PreproductionDataSourceGovernance.lifecycle_status == "ACTIVE",
        ))
        if governed is None:
            governed = db.scalar(select(DataSourceConnection).join(
                PreproductionDataSourceGovernance,
                PreproductionDataSourceGovernance.source_id == DataSourceConnection.source_id,
            ).where(
                DataSourceConnection.display_name == "P4 模拟 PostgreSQL",
                PreproductionDataSourceGovernance.lifecycle_status != "ARCHIVED",
            ).order_by(PreproductionDataSourceGovernance.version.desc()))
        if governed is None:
            governed = data_service.create(
                display_name="P4 模拟 PostgreSQL", source_type="postgresql", host="db", port=5432,
                database_name=ACCEPTANCE_DATABASE_NAME, username="alpha", credential_ref_id=datasource_ref.credential_ref_id,
                scenario_id="charging_ops", connection_options={"write_access": False},
            )
        governance = db.scalar(select(PreproductionDataSourceGovernance).where(
            PreproductionDataSourceGovernance.source_id == governed.source_id,
        ))
        if governance.lifecycle_status == "DRAFT":
            options = json.loads(governed.connection_options_json or "{}")
            if options.get("connection_test", {}).get("status") != "PASS":
                data_service.test_connection(governed.source_id)
            if options.get("schema_discovery", {}).get("status") != "PASS":
                data_service.discover_schema(governed.source_id)
            if options.get("profile", {}).get("status") != "PASS":
                data_service.profile(governed.source_id, relation="public.fact_charging_session")
            data_service.submit(governed.source_id)
        if governance.lifecycle_status == "REVIEW":
            data_service.approve(governed.source_id)
        if governance.lifecycle_status == "APPROVED":
            data_service.publish(governed.source_id)
        if governance.lifecycle_status == "PUBLISHED":
            governed = data_service.activate(governed.source_id)

        governed_state = db.scalar(select(PreproductionDataSourceGovernance.lifecycle_status).where(
            PreproductionDataSourceGovernance.source_id == governed.source_id,
        ))
        metrics = {
            "charging_sessions": charging["sessions"],
            "sales_orders": sales.order_count,
            "sales_order_items": sales.order_item_count,
            "datasource_status": governed_state,
            "credential_references": int(db.scalar(select(func.count()).select_from(CredentialReference)) or 0),
        }
        evidence_hash = hashlib.sha256(json.dumps(metrics, sort_keys=True).encode()).hexdigest()
        run_id = "P4-INIT-FIXED-SEED-20260801"
        existing = db.scalar(select(PreproductionAcceptanceRecord).where(
            PreproductionAcceptanceRecord.run_id == run_id,
            PreproductionAcceptanceRecord.category == "DATA_SOURCE_GOVERNANCE",
        ))
        if existing is None:
            now = datetime.now(UTC)
            db.add(PreproductionAcceptanceRecord(
                acceptance_id="ACC-P4-DATASOURCE-INIT", run_id=run_id,
                category="DATA_SOURCE_GOVERNANCE", status="PASS", environment="preproduction",
                metrics_json=json.dumps(metrics, sort_keys=True), evidence_hash=evidence_hash,
                data_classification="simulated", started_at=now, finished_at=now,
                created_by=identity.subject_id,
            ))
        db.commit()
    print(json.dumps({
        "status": "PASS", "revision": revision, "data_classification": "simulated",
        "period_start": "2025-01-01", "period_end_inclusive": "2026-06-30",
        "charging_seed": CHARGING_SEED, "sales_seed": DEFAULT_SEED,
        "charging": charging, "charging_platform": charging_platform,
        "ingestion": ingestion, "sales": sales.as_dict(), "sales_platform": sales_platform,
        "datasource_lifecycle": governed_state, "secret_values_printed": False,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
