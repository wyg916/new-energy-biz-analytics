from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.governance.audit import record_governance_event
from app.governance.contracts import AuthorizationContext, AuthorizationDecision
from app.governance.models import (
    GovernanceBinding,
    GovernancePermission,
    GovernancePolicy,
    GovernanceRole,
    GovernanceRolePermission,
    IdentityGroup,
    IdentityGroupMembership,
)
from app.platform.identity import IdentityContext


class AuthorizationDenied(PermissionError):
    def __init__(self, decision: AuthorizationDecision) -> None:
        super().__init__(decision.reason)
        self.decision = decision
        self.code = decision.code


def _matches(value: str, patterns: list[str]) -> bool:
    return "*" in patterns or value in patterns or any(
        pattern.endswith(".*") and value.startswith(pattern[:-1]) for pattern in patterns
    )


class AuthorizationService:
    """Database-backed RBAC plus deterministic ABAC; every unmatched request is denied."""

    def __init__(self, db: Session, identity: IdentityContext) -> None:
        self.db = db
        self.identity = identity

    def decide(self, context: AuthorizationContext) -> AuthorizationDecision:
        if context.tenant_id != self.identity.tenant_id:
            return self._denied(context, "CROSS_TENANT_DENIED", "请求租户与可信身份不一致", "authorization.cross_tenant")
        if context.workspace_id != self.identity.workspace_id:
            return self._denied(context, "CROSS_WORKSPACE_DENIED", "请求工作区与可信身份不一致")
        group_ids = self._active_group_ids()
        assigned_role_ids: set[str] = set()
        subject_filters = []
        if self.identity.principal_id:
            subject_filters.append(GovernanceBinding.principal_id == self.identity.principal_id)
        if group_ids:
            subject_filters.append(GovernanceBinding.group_id.in_(group_ids))
        if subject_filters:
            assigned_role_ids.update(self.db.scalars(select(GovernanceBinding.role_id).where(
                GovernanceBinding.tenant_id == self.identity.tenant_id,
                GovernanceBinding.workspace_id == self.identity.workspace_id,
                GovernanceBinding.policy_id.is_(None),
                GovernanceBinding.role_id.is_not(None),
                GovernanceBinding.status == "ACTIVE",
                or_(*subject_filters),
                or_(GovernanceBinding.expires_at.is_(None), GovernanceBinding.expires_at > datetime.now(UTC)),
            )).all())
        role_filters = []
        if self.identity.roles:
            role_filters.append(GovernanceRole.role_code.in_(self.identity.roles))
        if assigned_role_ids:
            role_filters.append(GovernanceRole.role_id.in_(assigned_role_ids))
        roles = list(self.db.scalars(select(GovernanceRole).where(
            GovernanceRole.tenant_id == self.identity.tenant_id,
            GovernanceRole.status == "ACTIVE",
            or_(*role_filters),
        )).all()) if role_filters else []
        if not roles:
            return self._denied(context, "RBAC_ROLE_NOT_BOUND", "身份没有 ACTIVE 角色")
        role_ids = tuple(role.role_id for role in roles)
        permission_rows = self.db.execute(select(
            GovernanceRolePermission.effect,
            GovernancePermission.permission_code,
        ).join(
            GovernancePermission,
            GovernanceRolePermission.permission_id == GovernancePermission.permission_id,
        ).where(
            GovernanceRolePermission.role_id.in_(role_ids),
            GovernancePermission.permission_code == context.action,
        )).all()
        if not permission_rows or any(effect == "DENY" for effect, _ in permission_rows):
            return self._denied(context, "RBAC_PERMISSION_DENIED", "角色未授予所需权限")

        policy_subject_filters = [GovernanceBinding.role_id.in_(role_ids)]
        if self.identity.principal_id:
            policy_subject_filters.append(GovernanceBinding.principal_id == self.identity.principal_id)
        if group_ids:
            policy_subject_filters.append(GovernanceBinding.group_id.in_(group_ids))
        policy_rows = self.db.execute(select(GovernancePolicy, GovernanceBinding).join(
            GovernanceBinding,
            GovernanceBinding.policy_id == GovernancePolicy.policy_id,
        ).where(
            GovernancePolicy.tenant_id == self.identity.tenant_id,
            GovernancePolicy.workspace_id == self.identity.workspace_id,
            GovernancePolicy.status == "ACTIVE",
            GovernancePolicy.approved_by.is_not(None),
            GovernanceBinding.tenant_id == self.identity.tenant_id,
            GovernanceBinding.workspace_id == self.identity.workspace_id,
            GovernanceBinding.status == "ACTIVE",
            or_(*policy_subject_filters),
            or_(GovernanceBinding.scenario_id.is_(None), GovernanceBinding.scenario_id == context.scenario_id),
            or_(GovernanceBinding.resource_type == "*", GovernanceBinding.resource_type == context.resource_type),
            or_(GovernanceBinding.resource_id.is_(None), GovernanceBinding.resource_id == context.resource_id),
            GovernanceBinding.environment == context.environment,
            or_(GovernanceBinding.expires_at.is_(None), GovernanceBinding.expires_at > datetime.now(UTC)),
        )).all()
        matched: list[str] = []
        explicit_deny = False
        for policy, _binding in policy_rows:
            actions = list(json.loads(policy.actions_json))
            resources = list(json.loads(policy.resource_types_json))
            if not _matches(context.action, actions) or not _matches(context.resource_type, resources):
                continue
            if not self._conditions_match(context, json.loads(policy.conditions_json)):
                continue
            matched.append(policy.policy_id)
            if policy.effect == "DENY":
                explicit_deny = True
        if explicit_deny:
            return self._denied(context, "ABAC_EXPLICIT_DENY", "Policy 明确拒绝该访问")
        if not matched:
            return self._denied(context, "ABAC_POLICY_NOT_MATCHED", "没有匹配的 ACTIVE Policy")
        return AuthorizationDecision(
            allowed=True,
            code="AUTHORIZED",
            reason="RBAC 与 ABAC 均通过",
            permission=context.action,
            matched_role_ids=role_ids,
            matched_policy_ids=tuple(matched),
        )

    def require(self, context: AuthorizationContext) -> AuthorizationDecision:
        decision = self.decide(context)
        if not decision.allowed:
            raise AuthorizationDenied(decision)
        return decision

    def _conditions_match(self, context: AuthorizationContext, conditions: dict) -> bool:
        scenarios = conditions.get("scenarios", ["charging_ops", "sales_ops"])
        if context.scenario_id is not None and not _matches(context.scenario_id, scenarios):
            return False
        classifications = conditions.get("data_classifications", ["simulated", "internal", "public"])
        if not _matches(context.data_classification, classifications):
            return False
        environments = conditions.get("environments", ["development", "test", "staging"])
        if not _matches(context.environment, environments):
            return False
        owner_actions = conditions.get("owner_enforced_actions", [])
        if _matches(context.action, owner_actions) and "analyst_admin" not in self.identity.roles:
            if not context.owner_subject_id or context.owner_subject_id != self.identity.subject_id:
                return False
        required = conditions.get("required_attributes", {})
        return all(context.attributes.get(key) == value for key, value in required.items())

    def _denied(
        self,
        context: AuthorizationContext,
        code: str,
        reason: str,
        action: str = "authorization.denied",
    ) -> AuthorizationDecision:
        record_governance_event(
            self.db,
            self.identity,
            action=action,
            resource_type=context.resource_type,
            resource_id=context.resource_id,
            result="DENIED",
            trace_id=context.trace_id,
            detail={"permission": context.action, "code": code, "scenario_id": context.scenario_id},
            commit=True,
        )
        return AuthorizationDecision(False, code, reason, context.action)

    def _active_group_ids(self) -> set[str]:
        group_ids: set[str] = set()
        if self.identity.groups:
            group_ids.update(self.db.scalars(select(IdentityGroup.group_id).where(
                IdentityGroup.tenant_id == self.identity.tenant_id,
                IdentityGroup.workspace_id == self.identity.workspace_id,
                IdentityGroup.group_code.in_(self.identity.groups),
                IdentityGroup.status == "ACTIVE",
            )).all())
        if self.identity.principal_id:
            group_ids.update(self.db.scalars(select(IdentityGroupMembership.group_id).join(
                IdentityGroup,
                IdentityGroup.group_id == IdentityGroupMembership.group_id,
            ).where(
                IdentityGroupMembership.principal_id == self.identity.principal_id,
                IdentityGroupMembership.tenant_id == self.identity.tenant_id,
                IdentityGroupMembership.workspace_id == self.identity.workspace_id,
                IdentityGroupMembership.status == "ACTIVE",
                IdentityGroup.status == "ACTIVE",
            )).all())
        return group_ids


def request_context(
    identity: IdentityContext,
    *,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    scenario_id: str | None = None,
    owner_subject_id: str | None = None,
    data_classification: str = "simulated",
    environment: str = "development",
    trace_id: str | None = None,
) -> AuthorizationContext:
    return AuthorizationContext(
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        tenant_id=identity.tenant_id,
        workspace_id=identity.workspace_id,
        scenario_id=scenario_id,
        owner_subject_id=owner_subject_id,
        data_classification=data_classification,
        environment=environment,
        trace_id=trace_id,
    )
