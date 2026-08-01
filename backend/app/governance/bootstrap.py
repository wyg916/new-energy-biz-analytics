from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.governance.models import (
    GovernanceBinding,
    GovernancePermission,
    GovernancePolicy,
    GovernanceRole,
    GovernanceRolePermission,
    Principal,
    RetentionPolicy,
)
from app.models.auth import User


PERMISSIONS: dict[str, tuple[str, str, str]] = {
    "datasource.view": ("datasource", "view", "查看数据源"),
    "dataset.view": ("dataset", "view", "查看数据集"),
    "metric.query": ("metric", "query", "查询已发布指标"),
    "rag.document.view": ("rag_document", "view", "访问授权 RAG 文档"),
    "memory.view": ("memory", "view", "查看记忆"),
    "memory.confirm": ("memory", "confirm", "确认记忆"),
    "memory.correct": ("memory", "correct", "纠正记忆"),
    "memory.delete": ("memory", "delete", "删除记忆"),
    "skill.view": ("skill", "view", "查看 Skill"),
    "skill.execute": ("skill", "execute", "执行 Skill"),
    "procedure.review": ("procedure", "review", "审核 Procedure"),
    "procedure.activate": ("procedure", "activate", "激活 Procedure"),
    "procedure.disable": ("procedure", "disable", "停用 Procedure"),
    "procedure.rollback": ("procedure", "rollback", "回滚 Procedure"),
    "audit.view": ("audit", "view", "查看治理审计"),
    "audit.export": ("audit", "export", "导出治理审计"),
    "credential.manage": ("credential_reference", "manage", "管理凭据引用"),
    "credential.use": ("credential_reference", "use", "使用凭据引用"),
    "release.review": ("release", "review", "审核发布"),
    "release.activate": ("release", "activate", "激活发布"),
    "release.rollback": ("release", "rollback", "回滚发布"),
    "identity.manage": ("identity", "manage", "管理身份映射"),
    "policy.manage": ("policy", "manage", "管理授权策略"),
    "legal_hold.manage": ("legal_hold", "manage", "管理 Legal Hold"),
    "retention.manage": ("retention", "manage", "管理保留策略"),
    "alert.view": ("security_alert", "view", "查看站内安全告警"),
    "alert.manage": ("security_alert", "manage", "确认站内安全告警"),
    "health.view": ("runtime_health", "view", "查看运行健康"),
}

BUSINESS_PERMISSIONS = {
    "datasource.view", "dataset.view", "metric.query", "rag.document.view",
    "memory.view", "memory.confirm", "memory.correct", "memory.delete",
    "skill.view", "skill.execute", "health.view",
}


def install_governance_baseline(db: Session) -> None:
    settings = get_settings()
    users = list(db.scalars(select(User)).all())
    for user in users:
        principal_id = f"PRN-LOCAL-{user.id}"
        principal = db.get(Principal, principal_id)
        if principal is None:
            db.add(Principal(
                principal_id=principal_id,
                principal_type="USER",
                provider_code="LOCAL",
                external_subject=user.username,
                local_user_id=user.id,
                tenant_id=settings.platform_tenant_id,
                organization_id=settings.platform_org_id,
                workspace_id=settings.platform_workspace_id,
                display_name=user.display_name,
                status="ACTIVE",
                auth_strength="local-jwt",
                attributes_json=json.dumps({"roles": [user.role]}, sort_keys=True),
            ))

    for code, (resource_type, action, description) in PERMISSIONS.items():
        permission_id = f"PERM-{code.replace('.', '-').upper()}"
        if db.get(GovernancePermission, permission_id) is None:
            db.add(GovernancePermission(
                permission_id=permission_id,
                permission_code=code,
                resource_type=resource_type,
                action=action,
                description=description,
            ))
    db.flush()

    role_permissions = {
        "executive": BUSINESS_PERMISSIONS,
        "regional_manager": BUSINESS_PERMISSIONS,
        "analyst_admin": set(PERMISSIONS),
    }
    roles: dict[str, GovernanceRole] = {}
    for role_code, permission_codes in role_permissions.items():
        role_id = f"ROLE-{role_code.upper()}"
        role = db.get(GovernanceRole, role_id)
        if role is None:
            role = GovernanceRole(
                role_id=role_id,
                tenant_id=settings.platform_tenant_id,
                role_code=role_code,
                display_name=role_code,
                status="ACTIVE",
                system_managed=True,
            )
            db.add(role)
        roles[role_code] = role
        for permission_code in permission_codes:
            permission = db.scalar(select(GovernancePermission).where(
                GovernancePermission.permission_code == permission_code
            ))
            binding_id = f"RP-{role_code}-{permission_code}".replace(".", "-").upper()
            if db.get(GovernanceRolePermission, binding_id) is None:
                db.add(GovernanceRolePermission(
                    role_permission_id=binding_id,
                    role_id=role_id,
                    permission_id=permission.permission_id,
                    effect="ALLOW",
                ))

    policy_id = "POLICY-P3-PLATFORM-SCOPE-V1"
    policy = db.get(GovernancePolicy, policy_id)
    if policy is None:
        policy = GovernancePolicy(
            policy_id=policy_id,
            tenant_id=settings.platform_tenant_id,
            workspace_id=settings.platform_workspace_id,
            policy_code="p3-platform-scope",
            version=1,
            status="ACTIVE",
            effect="ALLOW",
            actions_json=json.dumps(["*"], sort_keys=True),
            resource_types_json=json.dumps(["*"], sort_keys=True),
            conditions_json=json.dumps({
                "scenarios": ["charging_ops", "sales_ops"],
                "data_classifications": ["simulated", "internal", "public"],
                "environments": ["development", "test", "staging"],
                "owner_enforced_actions": ["memory.confirm", "memory.correct", "memory.delete"],
            }, sort_keys=True),
            approved_by="system:p3-baseline",
            approved_at=datetime.now(UTC),
            created_by="system:p3-baseline",
        )
        db.add(policy)
    for role_code, role in roles.items():
        binding_id = f"BIND-P3-{role_code.upper()}"
        if db.get(GovernanceBinding, binding_id) is None:
            db.add(GovernanceBinding(
                binding_id=binding_id,
                tenant_id=settings.platform_tenant_id,
                workspace_id=settings.platform_workspace_id,
                role_id=role.role_id,
                policy_id=policy_id,
                resource_type="*",
                environment=settings.app_env,
                status="ACTIVE",
                created_by="system:p3-baseline",
            ))
    if db.get(RetentionPolicy, "RET-P3-GOVERNANCE-V1") is None:
        db.add(RetentionPolicy(
            retention_policy_id="RET-P3-GOVERNANCE-V1",
            policy_code="p3-governance-default",
            version=1,
            tenant_id=settings.platform_tenant_id,
            workspace_id=settings.platform_workspace_id,
            resource_type="governance_audit",
            retention_days=365,
            archive_after_days=180,
            deletion_mode="ANONYMIZE",
            status="ACTIVE",
            approved_by="system:p3-baseline",
            approved_at=datetime.now(UTC),
            created_by="system:p3-baseline",
        ))
    db.commit()
