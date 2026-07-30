from dataclasses import replace
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.platform.identity import IdentityContext
from app.platform.query_engine import QueryRequest
from app.query_engines.router import CanaryPolicy


pytestmark = pytest.mark.no_db


def _production_values() -> dict:
    return {
        "app_env": "production",
        "database_url": (
            "postgresql+psycopg://renewable:strong-db-password"
            "@db:5432/renewable_private"
        ),
        "redis_url": "redis://redis:6379/0",
        "secret_key": "a-secure-private-release-secret-key",
        "auto_bootstrap_demo_users": False,
        "public_base_url": "https://analytics.example.internal",
        "cors_origins": "https://analytics.example.internal",
        "trusted_hosts": "analytics.example.internal",
        "release_version": "0.6.0-rc1",
        "simulated_data_only": True,
    }


def _identity(**overrides) -> IdentityContext:
    values = {
        "subject_id": "user:canary",
        "tenant_id": "tenant-alpha",
        "org_id": "org-alpha",
        "workspace_id": "workspace-alpha",
        "roles": ("analyst",),
        "groups": (),
        "data_scopes": ("workspace:all",),
        "auth_strength": "test",
        "issued_at": datetime.now(UTC),
        "request_id": "request-canary-1",
    }
    values.update(overrides)
    return IdentityContext(**values)


def _request(
    identity: IdentityContext | None = None,
    *,
    scenario_id: str = "sales_ops",
) -> QueryRequest:
    return QueryRequest(
        question="按区域查看销售额",
        identity_context=identity or _identity(),
        scenario_id=scenario_id,
    )


def test_platform_version_routing_defaults_and_immediate_rollback(
    monkeypatch,
) -> None:
    monkeypatch.delenv("PLATFORM_VERSION_ROUTING_ENABLED", raising=False)
    assert Settings(
        app_env="development",
        platform_version_routing_enabled=None,
    ).effective_platform_version_routing_enabled is True
    assert Settings(
        app_env="test",
        platform_version_routing_enabled=None,
    ).effective_platform_version_routing_enabled is True

    production = Settings(
        **_production_values(),
        platform_version_routing_enabled=None,
    )
    assert production.effective_platform_version_routing_enabled is False
    assert production.effective_query_engine_mode == "DETERMINISTIC_ONLY"

    rollback = Settings(
        app_env="development",
        platform_version_routing_enabled=False,
        query_engine_mode="DETERMINISTIC_ONLY",
    )
    assert rollback.effective_platform_version_routing_enabled is False
    assert rollback.effective_query_engine_mode == "DETERMINISTIC_ONLY"


def test_production_rejects_enabled_platform_version_routing() -> None:
    with pytest.raises(ValidationError, match="must be false"):
        Settings(
            **_production_values(),
            platform_version_routing_enabled=True,
        )


def test_canary_scope_requires_tenant_workspace_user_and_scenario() -> None:
    policy = CanaryPolicy(
        percentage=100,
        tenants=frozenset({"tenant-alpha"}),
        workspaces=frozenset({"workspace-alpha"}),
        users=frozenset({"user:canary"}),
        scenarios=frozenset({"charging_ops", "sales_ops"}),
    )
    request = _request()
    assert policy.eligible(request) is True
    assert policy.eligible(request) is True
    assert policy.eligible(_request(_identity(tenant_id="tenant-other"))) is False
    assert policy.eligible(
        _request(_identity(workspace_id="workspace-other"))
    ) is False
    assert policy.eligible(
        _request(_identity(subject_id="user:other"))
    ) is False
    assert policy.eligible(
        _request(scenario_id="other_ops")
    ) is False

    zero = replace(policy, percentage=0)
    assert zero.eligible(request) is False
