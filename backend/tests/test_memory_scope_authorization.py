from datetime import UTC, datetime

import pytest

from app.memory.authorization import MemoryAuthorization, MemoryAuthorizationError
from app.memory.contracts import MemoryScope
from app.memory.models import MemoryRecord
from app.platform.identity import IdentityContext


def identity(*, subject="user:1", tenant="tenant-a", org="org-a", workspace="workspace-a", role="analyst"):
    return IdentityContext(
        subject_id=subject,
        tenant_id=tenant,
        org_id=org,
        workspace_id=workspace,
        roles=(role,),
        groups=(),
        data_scopes=("workspace:all",),
        auth_strength="test",
        issued_at=datetime.now(UTC),
        request_id="REQ-memory-auth",
    )


def record(**overrides):
    values = {
        "memory_id": "MEM-1",
        "memory_type": "SEMANTIC",
        "scope_type": "USER",
        "tenant_id": "tenant-a",
        "organization_id": "org-a",
        "workspace_id": "workspace-a",
        "user_id": "user:1",
        "scenario_id": "charging_ops",
        "content": "偏好简洁回答",
        "structured_value_json": "{}",
        "source_type": "USER_STATEMENT",
        "trust_level": "USER_CONFIRMED",
        "status": "ACTIVE",
        "duplicate_hash": "a" * 64,
    }
    values.update(overrides)
    return MemoryRecord(**values)


@pytest.mark.no_db
@pytest.mark.parametrize(
    ("scope", "kwargs", "expected_user"),
    [
        (MemoryScope.TENANT, {}, None),
        (MemoryScope.WORKSPACE, {}, None),
        (MemoryScope.USER, {}, "user:1"),
        (MemoryScope.AGENT, {"agent_id": "chatbi"}, "user:1"),
        (MemoryScope.SESSION, {"session_id": "CONV-1"}, "user:1"),
        (MemoryScope.RUN, {"run_id": "RUN-1"}, "user:1"),
    ],
)
def test_scope_is_injected_from_identity(scope, kwargs, expected_user):
    scoped = MemoryAuthorization.scope_from_identity(
        identity(), scope, scenario_id="charging_ops", **kwargs
    )
    assert scoped.tenant_id == "tenant-a"
    assert scoped.workspace_id == "workspace-a"
    assert scoped.user_id == expected_user


@pytest.mark.no_db
@pytest.mark.parametrize(
    ("scope", "kwargs", "code"),
    [
        (MemoryScope.GLOBAL, {}, "GLOBAL_SCOPE_FORBIDDEN"),
        (MemoryScope.AGENT, {}, "AGENT_SCOPE_REQUIRED"),
        (MemoryScope.SESSION, {}, "SESSION_SCOPE_REQUIRED"),
        (MemoryScope.RUN, {}, "RUN_SCOPE_REQUIRED"),
    ],
)
def test_invalid_scope_is_rejected(scope, kwargs, code):
    with pytest.raises(MemoryAuthorizationError) as error:
        MemoryAuthorization.scope_from_identity(
            identity(), scope, scenario_id="charging_ops", **kwargs
        )
    assert error.value.code == code


@pytest.mark.no_db
@pytest.mark.parametrize(
    ("changed", "code"),
    [
        ({"tenant_id": "tenant-b"}, "CROSS_TENANT_DENIED"),
        ({"organization_id": "org-b"}, "CROSS_ORGANIZATION_DENIED"),
        ({"workspace_id": "workspace-b"}, "CROSS_WORKSPACE_DENIED"),
        ({"user_id": "user:2"}, "CROSS_USER_DENIED"),
    ],
)
def test_cross_scope_record_is_rejected(changed, code):
    with pytest.raises(MemoryAuthorizationError) as error:
        MemoryAuthorization.assert_owned(identity(), record(**changed))
    assert error.value.code == code


@pytest.mark.no_db
def test_cross_scenario_record_is_rejected():
    with pytest.raises(MemoryAuthorizationError) as error:
        MemoryAuthorization.assert_scenario(record(), "sales_ops")
    assert error.value.code == "CROSS_SCENARIO_DENIED"


@pytest.mark.no_db
def test_admin_can_create_global_scope():
    scoped = MemoryAuthorization.scope_from_identity(
        identity(role="analyst_admin"), MemoryScope.GLOBAL, scenario_id=None
    )
    assert scoped.scope_type is MemoryScope.GLOBAL
    assert scoped.user_id is None
