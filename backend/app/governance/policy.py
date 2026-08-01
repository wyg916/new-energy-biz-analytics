from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.governance.audit import record_governance_event
from app.governance.authorization import AuthorizationService, request_context
from app.governance.contracts import GovernanceStatus
from app.governance.models import GovernanceBinding, GovernancePolicy, GovernanceRole
from app.platform.identity import IdentityContext


class PolicyGovernanceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class PolicyGovernanceService:
    def __init__(self, db: Session, identity: IdentityContext) -> None:
        self.db = db
        self.identity = identity

    def create(
        self,
        *,
        policy_code: str,
        effect: str,
        actions: list[str],
        resource_types: list[str],
        conditions: dict,
    ) -> GovernancePolicy:
        self._authorize(policy_code)
        if effect not in {"ALLOW", "DENY"} or not actions or not resource_types:
            raise PolicyGovernanceError("POLICY_DEFINITION_INVALID", "Policy effect、action 和 resource 均必须明确")
        version = int(self.db.scalar(select(func.max(GovernancePolicy.version)).where(
            GovernancePolicy.tenant_id == self.identity.tenant_id,
            GovernancePolicy.policy_code == policy_code,
        )) or 0) + 1
        policy = GovernancePolicy(
            policy_id=f"POLICY-{uuid4()}",
            tenant_id=self.identity.tenant_id,
            workspace_id=self.identity.workspace_id,
            policy_code=policy_code,
            version=version,
            status=GovernanceStatus.DRAFT,
            effect=effect,
            actions_json=json.dumps(sorted(set(actions)), sort_keys=True),
            resource_types_json=json.dumps(sorted(set(resource_types)), sort_keys=True),
            conditions_json=json.dumps(conditions, ensure_ascii=False, sort_keys=True),
            created_by=self.identity.subject_id,
        )
        self.db.add(policy)
        self._audit(policy, "policy.created", "SUCCESS")
        self.db.commit()
        return policy

    def submit_review(self, policy_id: str) -> GovernancePolicy:
        policy = self._owned(policy_id)
        self._authorize(policy_id)
        if policy.status != GovernanceStatus.DRAFT:
            raise PolicyGovernanceError("POLICY_INVALID_TRANSITION", "只有 DRAFT Policy 可以提交审核")
        policy.status = GovernanceStatus.REVIEW
        policy.updated_at = datetime.now(UTC)
        self._audit(policy, "policy.review_submitted", "SUCCESS")
        self.db.commit()
        return policy

    def approve(self, policy_id: str) -> GovernancePolicy:
        policy = self._owned(policy_id)
        self._authorize(policy_id)
        if policy.status != GovernanceStatus.REVIEW:
            raise PolicyGovernanceError("POLICY_NOT_REVIEWED", "未经 REVIEW 的 Policy 不能批准")
        policy.status = GovernanceStatus.APPROVED
        policy.approved_by = self.identity.subject_id
        policy.approved_at = datetime.now(UTC)
        policy.updated_at = datetime.now(UTC)
        self._audit(policy, "policy.approved", "SUCCESS")
        self.db.commit()
        return policy

    def activate(self, policy_id: str) -> GovernancePolicy:
        policy = self._owned(policy_id)
        self._authorize(policy_id)
        if policy.status != GovernanceStatus.APPROVED or not policy.approved_by:
            record_governance_event(
                self.db, self.identity,
                action="policy.activate_denied",
                resource_type="policy",
                resource_id=policy_id,
                result="DENIED",
                detail={"status": policy.status},
                commit=True,
            )
            raise PolicyGovernanceError("POLICY_NOT_APPROVED", "未审核 Policy 不能 ACTIVE")
        existing = list(self.db.scalars(select(GovernancePolicy).where(
            GovernancePolicy.tenant_id == self.identity.tenant_id,
            GovernancePolicy.workspace_id == self.identity.workspace_id,
            GovernancePolicy.policy_code == policy.policy_code,
            GovernancePolicy.status == GovernanceStatus.ACTIVE,
        )).all())
        for row in existing:
            row.status = GovernanceStatus.SUPERSEDED
            row.updated_at = datetime.now(UTC)
        policy.status = GovernanceStatus.ACTIVE
        policy.updated_at = datetime.now(UTC)
        self._audit(policy, "policy.activated", "SUCCESS")
        self.db.commit()
        return policy

    def bind(
        self,
        policy_id: str,
        *,
        role_code: str,
        scenario_id: str | None,
        resource_type: str,
        resource_id: str | None,
        environment: str,
    ) -> GovernanceBinding:
        policy = self._owned(policy_id)
        self._authorize(policy_id)
        if policy.status != GovernanceStatus.ACTIVE:
            raise PolicyGovernanceError("POLICY_NOT_ACTIVE", "只有 ACTIVE Policy 可以创建生效绑定")
        role = self.db.scalar(select(GovernanceRole).where(
            GovernanceRole.tenant_id == self.identity.tenant_id,
            GovernanceRole.role_code == role_code,
            GovernanceRole.status == "ACTIVE",
        ))
        if role is None:
            raise PolicyGovernanceError("ROLE_NOT_ACTIVE", "绑定角色不存在或未生效")
        binding = GovernanceBinding(
            binding_id=f"BIND-{uuid4()}",
            tenant_id=self.identity.tenant_id,
            workspace_id=self.identity.workspace_id,
            role_id=role.role_id,
            policy_id=policy.policy_id,
            scenario_id=scenario_id,
            resource_type=resource_type,
            resource_id=resource_id,
            environment=environment,
            status="ACTIVE",
            created_by=self.identity.subject_id,
        )
        self.db.add(binding)
        self._audit(policy, "policy.binding_created", "SUCCESS", {"binding_id": binding.binding_id, "role_code": role_code})
        self.db.commit()
        return binding

    def _owned(self, policy_id: str) -> GovernancePolicy:
        policy = self.db.get(GovernancePolicy, policy_id)
        if policy is None or policy.tenant_id != self.identity.tenant_id or policy.workspace_id != self.identity.workspace_id:
            raise PolicyGovernanceError("POLICY_NOT_FOUND", "Policy 不存在")
        return policy

    def _authorize(self, resource_id: str) -> None:
        AuthorizationService(self.db, self.identity).require(request_context(
            self.identity,
            action="policy.manage",
            resource_type="policy",
            resource_id=resource_id,
            environment=get_settings().app_env,
        ))

    def _audit(self, policy: GovernancePolicy, action: str, result: str, detail: dict | None = None) -> None:
        record_governance_event(
            self.db, self.identity,
            action=action,
            resource_type="policy",
            resource_id=policy.policy_id,
            result=result,
            detail={"policy_code": policy.policy_code, "version": policy.version, **(detail or {})},
        )
