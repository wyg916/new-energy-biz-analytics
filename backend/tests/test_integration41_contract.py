from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings


ROOT = Path(__file__).resolve().parents[2]


def test_merge_revision_and_runtime_flags_are_frozen():
    migration = (ROOT / "backend/alembic/versions/integration_41_merge_0001.py").read_text(
        encoding="utf-8"
    )
    override = (ROOT / "deploy/data41/override.yaml").read_text(encoding="utf-8")

    assert 'revision = "integration_41_merge_0001"' in migration
    assert 'down_revision = ("memory_41_0001", "rag_0001")' in migration
    assert "EXPECTED_DATABASE_REVISION: integration_41_merge_0001" in override
    assert "MEMORY_LIFECYCLE_SCHEDULER_ENABLED: \"true\"" in override
    assert "start_period: 1800s" in override
    assert "QUERY_ENGINE_MODE: SHADOW" in override
    assert "SQLBOT_ENGINE_ENABLED: \"false\"" in override
    assert Settings().expected_database_revision == "integration_41_merge_0001"


def test_single_launcher_extends_integration_runtime_with_p6_gates():
    launcher = (ROOT / "一键启动.bat").read_text(encoding="utf-8-sig")
    startup = (ROOT / "scripts/release/start-project.ps1").read_text(encoding="utf-8-sig")

    assert "P6 4.1 Business Loop" in launcher
    assert "p6_41_0001" in launcher
    assert '$project = "renewable-p6-business-loop-41"' in startup
    assert '$expectedMigration = "p6_41_0001"' in startup
    assert '"renewable-integration41-core"' in startup
    assert 'query_engine_mode = "SHADOW"' in startup
    assert "verify_integration41_runtime.py" in startup
    assert '"python", "scripts/p4_entrypoint.py", "python", "scripts/rebuild_rag_indexes.py"' in startup
    assert '"python", "scripts/p4_entrypoint.py", "python", "scripts/verify_integration41_runtime.py"' in startup
    assert '"--expected-revision", $expectedMigration' in startup
    assert '"scripts/run_p3_migration_acceptance.py"' in startup
    assert '"--rollback-revision", "integration_41_merge_0001"' in startup
    assert '$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $workspace ".cache/ms-playwright"' in startup
    assert 'P6 runtime-only OIDC acceptance credential is unavailable' in startup
    assert '$env:P4_OIDC_PASSWORD = ($runtimePassword | Out-String).Trim()' in startup
    assert '"playwright", "install", "chromium"' in startup
    assert '"playwright", "test", "e2e/p6-business-loop.spec.ts"' in startup
    assert "[int]$TimeoutSeconds = 1800" in startup


def _preproduction_settings(**overrides):
    values = {
        "app_env": "preproduction",
        "database_url": (
            "postgresql+psycopg://integration:strong-db-password@db:5432/renewable_p5b"
        ),
        "redis_url": "redis://redis:6379/0",
        "secret_key": "integration-secret-key-with-safe-test-length",
        "auto_bootstrap_demo_users": False,
        "public_base_url": "https://p5b.localhost:8446",
        "cors_origins": "https://p5b.localhost:8446",
        "trusted_hosts": "p5b.localhost,localhost,api,testserver",
        "release_version": "4.1.0-integration.1",
        "simulated_data_only": False,
        "data41_open_source_enabled": True,
        "local_auth_enabled": False,
        "query_engine_mode": "SHADOW",
        "oidc_enabled": True,
        "oidc_issuer": "https://p5b.localhost:8446/oidc/realms/chatbi",
        "oidc_internal_base_url": "http://oidc:8080/oidc/realms/chatbi",
        "oidc_redirect_uri": "https://p5b.localhost:8446/oidc/callback",
        "vault_enabled": True,
        **overrides,
    }
    return Settings(**values)


def test_integration_preproduction_accepts_approved_open_source_data_mode():
    settings = _preproduction_settings()

    assert settings.simulated_data_only is False
    assert settings.data41_open_source_enabled is True


def test_p6_preproduction_inherits_approved_open_source_data_mode():
    settings = _preproduction_settings(release_version="4.1.0-p6.1")

    assert settings.simulated_data_only is False
    assert settings.data41_open_source_enabled is True


@pytest.mark.parametrize(
    "override",
    [
        {"data41_open_source_enabled": False},
        {"release_version": "4.0.0-rc.3"},
    ],
)
def test_open_source_data_mode_remains_fail_closed_outside_integration(override):
    with pytest.raises(ValidationError, match="SIMULATED_DATA_ONLY"):
        _preproduction_settings(**override)
