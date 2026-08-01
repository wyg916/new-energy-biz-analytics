from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.governance.audit import record_governance_event
from app.governance.authorization import AuthorizationService, request_context
from app.governance.contracts import GovernanceStatus
from app.governance.models import PlatformRelease
from app.platform.identity import IdentityContext


OBJECT_TYPES = {
    "SCENARIO_PACKAGE",
    "SEMANTIC_MODEL",
    "RAG_DOCUMENT",
    "PROCEDURE",
    "SKILL",
    "SQLBOT_SOURCE_BINDING",
    "POLICY_BUNDLE",
    "RELEASE_CANDIDATE",
}


class ReleaseGovernanceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ReleaseRegistry:
    def __init__(self, db: Session, identity: IdentityContext) -> None:
        self.db = db
        self.identity = identity

    def create(
        self,
        *,
        object_type: str,
        object_id: str,
        version: str,
        environment: str,
        artifact_hash: str,
        change_summary: str,
        metadata: dict | None = None,
    ) -> PlatformRelease:
        self._authorize("release.review", object_id)
        if object_type not in OBJECT_TYPES:
            raise ReleaseGovernanceError("RELEASE_OBJECT_TYPE_INVALID", "发布对象类型不受支持")
        release = PlatformRelease(
            release_id=f"REL-{uuid4()}",
            tenant_id=self.identity.tenant_id,
            workspace_id=self.identity.workspace_id,
            object_type=object_type,
            object_id=object_id,
            version=version,
            environment=environment,
            status=GovernanceStatus.DRAFT,
            artifact_hash=artifact_hash,
            change_summary=change_summary,
            metadata_json=json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
            created_by=self.identity.subject_id,
        )
        self.db.add(release)
        self._audit(release, "release.created", "SUCCESS")
        self.db.commit()
        return release

    def submit_review(self, release_id: str) -> PlatformRelease:
        release = self._owned(release_id)
        self._authorize("release.review", release_id)
        if release.status != GovernanceStatus.DRAFT:
            raise ReleaseGovernanceError("RELEASE_INVALID_TRANSITION", "只有 DRAFT 可以提交审核")
        release.status = GovernanceStatus.REVIEW
        release.reviewed_by = self.identity.subject_id
        release.reviewed_at = datetime.now(UTC)
        self._audit(release, "release.review_submitted", "SUCCESS")
        self.db.commit()
        return release

    def approve(self, release_id: str) -> PlatformRelease:
        release = self._owned(release_id)
        self._authorize("release.review", release_id)
        if release.status != GovernanceStatus.REVIEW:
            raise ReleaseGovernanceError("RELEASE_NOT_REVIEWED", "未经审核的版本不能批准")
        release.status = GovernanceStatus.APPROVED
        release.approved_by = self.identity.subject_id
        release.approved_at = datetime.now(UTC)
        self._audit(release, "release.approved", "SUCCESS")
        self.db.commit()
        return release

    def activate(self, release_id: str) -> PlatformRelease:
        release = self._owned(release_id)
        self._authorize("release.activate", release_id)
        if release.environment == "production":
            self._audit(release, "release.production_blocked", "DENIED")
            self.db.commit()
            raise ReleaseGovernanceError("PRODUCTION_RELEASE_DISABLED", "P3 不允许真实生产发布")
        if release.status != GovernanceStatus.APPROVED or not release.approved_by:
            self._audit(release, "release.activate_denied", "DENIED", {"status": release.status})
            self.db.commit()
            raise ReleaseGovernanceError("RELEASE_NOT_APPROVED", "未批准版本不能 ACTIVE")
        active = self.db.scalar(select(PlatformRelease).where(
            PlatformRelease.tenant_id == self.identity.tenant_id,
            PlatformRelease.workspace_id == self.identity.workspace_id,
            PlatformRelease.object_type == release.object_type,
            PlatformRelease.object_id == release.object_id,
            PlatformRelease.environment == release.environment,
            PlatformRelease.status == GovernanceStatus.ACTIVE,
        ).order_by(desc(PlatformRelease.activated_at)))
        if active:
            active.status = GovernanceStatus.SUPERSEDED
            release.supersedes_release_id = active.release_id
        release.status = GovernanceStatus.ACTIVE
        release.activated_by = self.identity.subject_id
        release.activated_at = datetime.now(UTC)
        self._audit(release, "release.activated", "SUCCESS")
        self.db.commit()
        return release

    def rollback(self, release_id: str, *, target_release_id: str) -> PlatformRelease:
        current = self._owned(release_id)
        target = self._owned(target_release_id)
        self._authorize("release.rollback", release_id)
        if current.status != GovernanceStatus.ACTIVE:
            raise ReleaseGovernanceError("RELEASE_NOT_ACTIVE", "只有 ACTIVE 版本可以回滚")
        if target.object_type != current.object_type or target.object_id != current.object_id or target.environment != current.environment:
            raise ReleaseGovernanceError("ROLLBACK_TARGET_MISMATCH", "回滚目标对象或环境不一致")
        if target.status not in {GovernanceStatus.SUPERSEDED, GovernanceStatus.APPROVED, GovernanceStatus.ROLLED_BACK}:
            raise ReleaseGovernanceError("ROLLBACK_TARGET_NOT_APPROVED", "回滚目标不是已批准历史版本")
        current.status = GovernanceStatus.ROLLED_BACK
        rollback_release = PlatformRelease(
            release_id=f"REL-{uuid4()}",
            tenant_id=current.tenant_id,
            workspace_id=current.workspace_id,
            object_type=current.object_type,
            object_id=current.object_id,
            version=f"{target.version}-rollback-{uuid4().hex[:8]}",
            environment=current.environment,
            status=GovernanceStatus.ACTIVE,
            artifact_hash=target.artifact_hash,
            change_summary=f"回滚到 {target.version}",
            metadata_json=target.metadata_json,
            created_by=self.identity.subject_id,
            reviewed_by=self.identity.subject_id,
            approved_by=self.identity.subject_id,
            activated_by=self.identity.subject_id,
            supersedes_release_id=current.release_id,
            rollback_of_release_id=current.release_id,
            reviewed_at=datetime.now(UTC),
            approved_at=datetime.now(UTC),
            activated_at=datetime.now(UTC),
        )
        self.db.add(rollback_release)
        self._audit(rollback_release, "release.rolled_back", "SUCCESS", {"target_release_id": target.release_id})
        self.db.commit()
        return rollback_release

    def _owned(self, release_id: str) -> PlatformRelease:
        release = self.db.get(PlatformRelease, release_id)
        if release is None or release.tenant_id != self.identity.tenant_id or release.workspace_id != self.identity.workspace_id:
            raise ReleaseGovernanceError("RELEASE_NOT_FOUND", "发布版本不存在")
        return release

    def _authorize(self, action: str, resource_id: str) -> None:
        AuthorizationService(self.db, self.identity).require(request_context(
            self.identity,
            action=action,
            resource_type="release",
            resource_id=resource_id,
            environment=get_settings().app_env,
        ))

    def _audit(self, release: PlatformRelease, action: str, result: str, detail: dict | None = None) -> None:
        record_governance_event(
            self.db, self.identity,
            action=action,
            resource_type="release",
            resource_id=release.release_id,
            result=result,
            detail={"object_type": release.object_type, "object_id": release.object_id, **(detail or {})},
        )
