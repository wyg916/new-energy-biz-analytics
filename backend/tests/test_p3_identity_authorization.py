from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.governance.authorization import AuthorizationService, request_context
from app.governance.contracts import AuthorizationContext
from app.governance.identity import (
    IdentityResolutionError,
    IdentityService,
    SignedLocalOIDCProvider,
)
from app.governance.models import Principal, SecurityAlert
from app.models.auth import User
from app.platform.identity import IdentityContextFactory


def test_trusted_identity_ignores_spoofed_scope_headers(client, login) -> None:
    headers = {
        **login(),
        "x-tenant-id": "tenant-attacker",
        "x-workspace-id": "workspace-attacker",
        "x-user-id": "user:attacker",
        "x-role": "super-admin",
    }
    response = client.get("/api/v1/governance/snapshot", headers=headers)
    assert response.status_code == 200, response.text
    identity = response.json()["identity"]
    assert identity["tenant_id"] == "tenant-alpha"
    assert identity["workspace_id"] == "workspace-alpha"
    assert identity["subject_id"] != "user:attacker"
    assert identity["roles"] == ["analyst_admin"]


def test_rbac_abac_default_deny_and_cross_scope_guards(client) -> None:
    with SessionLocal() as db:
        analyst = db.scalar(select(User).where(User.username == "analyst"))
        executive = db.scalar(select(User).where(User.username == "executive"))
        assert analyst and executive
        admin_identity = IdentityContextFactory.from_user(analyst, request_id="trace-auth-admin")
        executive_identity = IdentityContextFactory.from_user(executive, request_id="trace-auth-exec")

        allowed = AuthorizationService(db, admin_identity).decide(request_context(
            admin_identity,
            action="metric.query",
            resource_type="metric",
            scenario_id="charging_ops",
            environment="test",
        ))
        assert allowed.allowed is True

        cross_tenant = replace(
            request_context(
                admin_identity,
                action="metric.query",
                resource_type="metric",
                scenario_id="charging_ops",
                environment="test",
            ),
            tenant_id="tenant-attacker",
        )
        assert AuthorizationService(db, admin_identity).decide(cross_tenant).code == "CROSS_TENANT_DENIED"

        cross_workspace = replace(cross_tenant, tenant_id=admin_identity.tenant_id, workspace_id="workspace-attacker")
        assert AuthorizationService(db, admin_identity).decide(cross_workspace).code == "CROSS_WORKSPACE_DENIED"

        third_scenario = request_context(
            admin_identity,
            action="metric.query",
            resource_type="metric",
            scenario_id="unapproved_scenario",
            environment="test",
        )
        assert AuthorizationService(db, admin_identity).decide(third_scenario).code == "ABAC_POLICY_NOT_MATCHED"

        cross_user = request_context(
            executive_identity,
            action="memory.delete",
            resource_type="memory",
            owner_subject_id="user:someone-else",
            scenario_id="charging_ops",
            environment="test",
        )
        assert AuthorizationService(db, executive_identity).decide(cross_user).code == "ABAC_POLICY_NOT_MATCHED"

        model_claim = AuthorizationContext(
            action="policy.manage",
            resource_type="policy",
            tenant_id=executive_identity.tenant_id,
            workspace_id=executive_identity.workspace_id,
            scenario_id="charging_ops",
            environment="test",
            attributes={"model_requested_role": "analyst_admin", "allow": True},
        )
        assert AuthorizationService(db, executive_identity).decide(model_claim).code == "RBAC_PERMISSION_DENIED"

        alerts = list(db.scalars(select(SecurityAlert).where(SecurityAlert.status == "OPEN")).all())
        assert any(alert.rule_code == "CROSS_TENANT_ATTEMPT" for alert in alerts)


def test_oidc_provider_requires_preapproved_mapping(client) -> None:
    provider = SignedLocalOIDCProvider(
        issuer="https://local-idp.invalid",
        audience="chatbi-p3",
        signing_key="local-test-signing-key",
    )
    now = datetime.now(UTC)
    with SessionLocal() as db:
        db.add(Principal(
            principal_id="PRN-OIDC-APPROVED",
            principal_type="USER",
            provider_code="OIDC_LOCAL",
            external_subject="approved-subject",
            local_user_id=None,
            tenant_id="tenant-alpha",
            organization_id="org-alpha",
            workspace_id="workspace-alpha",
            display_name="Approved OIDC User",
            status="ACTIVE",
            auth_strength="oidc-mfa",
            attributes_json='{"roles":["analyst_admin"],"data_scopes":["workspace:all"]}',
        ))
        db.commit()
        token = jwt.encode(
            {
                "sub": "approved-subject",
                "iss": provider.issuer,
                "aud": provider.audience,
                "iat": now,
                "exp": now + timedelta(minutes=5),
                "tenant_id": "tenant-alpha",
                "groups": ["finance-analytics"],
            },
            provider.signing_key,
            algorithm="HS256",
        )
        identity = IdentityService(db).resolve_oidc(provider, token, request_id="trace-oidc")
        assert identity.principal_id == "PRN-OIDC-APPROVED"
        assert identity.roles == ("analyst_admin",)

        unknown = jwt.encode(
            {
                "sub": "unknown-subject",
                "iss": provider.issuer,
                "aud": provider.audience,
                "iat": now,
                "exp": now + timedelta(minutes=5),
            },
            provider.signing_key,
            algorithm="HS256",
        )
        try:
            IdentityService(db).resolve_oidc(provider, unknown, request_id="trace-unknown")
        except IdentityResolutionError as exc:
            assert exc.code == "OIDC_MAPPING_NOT_FOUND"
        else:
            raise AssertionError("unmapped OIDC subject must fail closed")

        assert get_settings().platform_tenant_id == identity.tenant_id
