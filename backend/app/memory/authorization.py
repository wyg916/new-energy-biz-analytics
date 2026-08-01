from __future__ import annotations

from sqlalchemy import and_, or_

from app.memory.contracts import MemoryScope, ScopeContext
from app.memory.models import MemoryRecord
from app.platform.identity import IdentityContext


class MemoryAuthorizationError(PermissionError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def identity_user_id(identity: IdentityContext) -> str:
    return identity.subject_id


class MemoryAuthorization:
    """Deterministic authorization enforced before storage or retrieval."""

    @staticmethod
    def scope_from_identity(
        identity: IdentityContext,
        scope_type: MemoryScope,
        *,
        scenario_id: str | None,
        agent_id: str | None = None,
        session_id: str | None = None,
        run_id: str | None = None,
    ) -> ScopeContext:
        if scope_type is MemoryScope.GLOBAL and "analyst_admin" not in identity.roles:
            raise MemoryAuthorizationError("GLOBAL_SCOPE_FORBIDDEN", "仅管理员可写入全局记忆")
        if scope_type is MemoryScope.AGENT and not agent_id:
            raise MemoryAuthorizationError("AGENT_SCOPE_REQUIRED", "AGENT 作用域必须提供 agent_id")
        if scope_type is MemoryScope.SESSION and not session_id:
            raise MemoryAuthorizationError("SESSION_SCOPE_REQUIRED", "SESSION 作用域必须提供 session_id")
        if scope_type is MemoryScope.RUN and not run_id:
            raise MemoryAuthorizationError("RUN_SCOPE_REQUIRED", "RUN 作用域必须提供 run_id")
        user_id = (
            identity_user_id(identity)
            if scope_type in {MemoryScope.USER, MemoryScope.AGENT, MemoryScope.SESSION, MemoryScope.RUN}
            else None
        )
        return ScopeContext(
            scope_type=scope_type,
            tenant_id=identity.tenant_id,
            organization_id=identity.org_id,
            workspace_id=identity.workspace_id,
            user_id=user_id,
            agent_id=agent_id,
            session_id=session_id,
            run_id=run_id,
            scenario_id=scenario_id,
        )

    @staticmethod
    def assert_owned(identity: IdentityContext, record: MemoryRecord) -> None:
        if record.tenant_id != identity.tenant_id:
            raise MemoryAuthorizationError("CROSS_TENANT_DENIED", "禁止跨租户访问记忆")
        if record.organization_id != identity.org_id:
            raise MemoryAuthorizationError("CROSS_ORGANIZATION_DENIED", "禁止跨组织访问记忆")
        if record.workspace_id != identity.workspace_id:
            raise MemoryAuthorizationError("CROSS_WORKSPACE_DENIED", "禁止跨工作区访问记忆")
        if record.user_id and record.user_id != identity_user_id(identity):
            raise MemoryAuthorizationError("CROSS_USER_DENIED", "禁止跨用户访问私有记忆")

    @staticmethod
    def assert_scenario(record: MemoryRecord, scenario_id: str) -> None:
        if record.scenario_id is not None and record.scenario_id != scenario_id:
            raise MemoryAuthorizationError("CROSS_SCENARIO_DENIED", "禁止跨场景访问私有记忆")

    @staticmethod
    def retrieval_filter(identity: IdentityContext, *, scenario_id: str):
        subject_id = identity_user_id(identity)
        return and_(
            MemoryRecord.tenant_id == identity.tenant_id,
            MemoryRecord.organization_id == identity.org_id,
            MemoryRecord.workspace_id == identity.workspace_id,
            or_(MemoryRecord.user_id.is_(None), MemoryRecord.user_id == subject_id),
            or_(MemoryRecord.scenario_id.is_(None), MemoryRecord.scenario_id == scenario_id),
        )
