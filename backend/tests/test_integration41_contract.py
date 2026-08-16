from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.no_db


def test_merge_revision_and_runtime_flags_are_frozen():
    core_migration = (ROOT / "backend/alembic/versions/integration_41_merge_0001.py").read_text(
        encoding="utf-8"
    )
    migration = (ROOT / "backend/alembic/versions/integration_41_full_0001_merge.py").read_text(
        encoding="utf-8"
    )
    override = (ROOT / "deploy/integration41full/override.yaml").read_text(encoding="utf-8")

    assert 'revision = "integration_41_merge_0001"' in core_migration
    assert 'down_revision = ("memory_41_0001", "rag_0001")' in core_migration
    assert 'revision = "integration_41_full_0001"' in migration
    assert 'down_revision = ("p6_41_0001", "sqlbot_41c2")' in migration
    assert "EXPECTED_DATABASE_REVISION: integration_41_full_0001" in override
    assert "ACCEPTANCE_POSTGRES_DB: renewable_p5b" in override
    assert "QUERY_ENGINE_MODE: DETERMINISTIC_ONLY" in override
    assert "SQLBOT_ENGINE_ENABLED: \"false\"" in override
    assert "SQLBOT_RUNTIME_VERIFIED: \"false\"" in override
    assert "SQLBOT_PROVIDER_ELIGIBILITY: REGISTERED_NOT_ELIGIBLE" in override
    assert "renewable-integration41-full-provider-credentials" in override
    assert Settings().expected_database_revision == "integration_41_full_0001"


def test_single_launcher_converges_full_integration_runtime():
    launcher = (ROOT / "一键启动.bat").read_text(encoding="utf-8-sig")
    startup = (ROOT / "scripts/release/start-project.ps1").read_text(encoding="utf-8-sig")
    stability = (ROOT / "scripts/Run-SQLBot41DStability.ps1").read_text(
        encoding="utf-8-sig"
    )
    canary = (ROOT / "scripts/Run-SQLBot41DCanary.ps1").read_text(
        encoding="utf-8-sig"
    )
    backend_regression = (
        ROOT / "scripts/Run-Integration41FullBackendRegression.ps1"
    ).read_text(encoding="utf-8-sig")
    backend_regression_entrypoint = (
        ROOT / "scripts/run_integration41full_backend_regression.sh"
    ).read_text(encoding="utf-8")
    override = (ROOT / "deploy/integration41full/override.yaml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "backend/Dockerfile").read_text(encoding="utf-8")

    assert "Full Integration 4.1" in launcher
    assert "integration_41_full_0001" in launcher
    assert "Open NL2SQL: disabled" in launcher
    assert "start-project.ps1" in launcher
    assert "-NoBrowser" not in launcher
    assert "Run-SQLBot41DOneClick.ps1" not in launcher
    assert "-SQLBotHostPort" not in launcher
    assert '$project = "renewable-integration41-full"' in startup
    assert "$configProperty.Value.PSObject.Properties['Labels']" in startup
    assert '$compatibilityCheck = "test -f /app/alembic/versions/integration_41_full_0001_merge.py && grep -q integration_41_full_0001' in startup
    assert "-lc $compatibilityCheck" in startup
    assert "--entrypoint sh $Image -lc @\"" not in startup
    assert '$expectedMigration = "integration_41_full_0001"' in startup
    assert '"renewable-integration41-core"' in startup
    assert 'query_engine_mode = "DETERMINISTIC_ONLY"' in startup
    assert 'sqlbot_runtime = "REGISTERED_NOT_ELIGIBLE_ENGINE_DISABLED"' in startup
    assert 'sqlbot_traffic_enabled = $false' in startup
    assert '"Provider credential references"' in startup
    assert '"Runtime ModelGateway provider calls"' in startup
    assert "run_runtime_model_gateway_probe.py" in startup
    assert "verify_integration41_runtime.py" in startup
    assert "prepare_integration41_full.py" in override
    assert "PENDING_GOVERNED_API" in startup
    assert "apply_knowledge_baseline_bootstrap.py" in startup
    assert '"scripts/rebuild_rag_indexes.py"' in startup
    assert startup.index("apply_knowledge_baseline_bootstrap.py") < startup.index("scripts/rebuild_rag_indexes.py")
    assert "COPY integration/knowledge_import_plan.json /app/integration/knowledge_import_plan.json" in dockerfile
    assert "COPY deploy/sqlbot/provision_platform_readonly_runtime.py /app/scripts/provision_platform_readonly_runtime.py" in dockerfile
    assert "provision_platform_readonly_runtime.py" in startup
    assert '"scripts/provision_platform_readonly_runtime.py"' in startup
    assert "activate_sqlbot41c2_source_bindings.py" in startup
    assert '"python", "scripts/p4_entrypoint.py", "python", "scripts/verify_integration41_runtime.py"' in startup
    assert '"--expected-revision", $expectedMigration' in startup
    assert '"scripts/run_p3_migration_acceptance.py"' in startup
    assert '"--rollback-revision", "integration_41_merge_0001"' in startup
    assert '"--rollback-via-revision", "data_0001"' in startup
    assert "[string]$Output" in stability
    assert "[string]$PlatformNetwork" in stability
    assert "resource_monitor_started_before_window" in stability
    assert stability.index("Get-SQLBotRuntimeSample -Phase 'pre_window'") < stability.index(
        "docker start $AcceptanceContainer"
    )
    assert "[string]$EvidenceDirectory" in canary
    assert "[string]$SQLBotRuntimeContainer" in canary
    assert '"VAULT_ADDRESS=http://${VaultContainer}:8200"' in canary
    assert "$PlatformApiImage" in canary
    one_click = (ROOT / "scripts/Run-SQLBot41DOneClick.ps1").read_text(
        encoding="utf-8-sig"
    )
    assert "Sync-SQLBot41CCredentialReference.ps1" in one_click
    assert '"http://${SQLBotContainer}:8000/api/v1"' in one_click
    assert "credential_sync" in one_click
    assert "python -m pytest backend/tests -q" in backend_regression
    assert "scripts/run_integration41full_backend_regression.sh" in backend_regression
    assert "python -m pytest backend/tests -q" in backend_regression_entrypoint
    assert "MEMORY41_TEST_REDIS_URL" in backend_regression_entrypoint
    assert "isolated tmpfs PostgreSQL 16.14" in backend_regression
    assert '$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $workspace ".cache/ms-playwright"' in startup
    assert 'P6 runtime-only OIDC acceptance credential is unavailable' in startup
    assert '$env:P4_OIDC_PASSWORD = ($runtimePassword | Out-String).Trim()' in startup
    assert '"playwright", "install", "chromium"' in startup
    assert '"playwright", "test", "e2e/p6-business-loop.spec.ts"' in startup
    assert "[int]$TimeoutSeconds = 1800" in startup


def test_local_oidc_login_is_discoverable_without_hardcoded_secret():
    launcher = (ROOT / "一键启动.bat").read_text(encoding="utf-8-sig")
    credential_launcher = (ROOT / "复制本地登录密码.bat").read_text(
        encoding="utf-8-sig"
    )
    helper = (ROOT / "scripts/release/Copy-LocalOidcPassword.ps1").read_text(
        encoding="utf-8-sig"
    )
    readme = (ROOT / "README.md").read_text(encoding="utf-8-sig")

    assert "Login username: p4.analyst" in launcher
    assert "Copy-LocalOidcPassword.ps1" in credential_launcher
    assert 'Username: p4.analyst' in helper
    assert '${project}_p4_keycloak_runtime' in helper
    assert '/run/p4-keycloak/keycloak_user_password' in helper
    assert 'Set-Clipboard -Value $runtimePassword' in helper
    assert 'Get-Clipboard -Raw' in helper
    assert 'Write-Host $runtimePassword' not in helper
    assert 'Write-Output $runtimePassword' not in helper
    assert '`p4.analyst`' in readme
    assert '复制本地登录密码.bat' in readme


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


def test_full_integration_preproduction_inherits_approved_open_source_data_mode():
    settings = _preproduction_settings(
        release_version="4.1.0-integration-full.1",
        query_engine_mode="DETERMINISTIC_ONLY",
        sqlbot_included_in_v4_release=True,
        sqlbot_provider_eligibility="REGISTERED_NOT_ELIGIBLE",
    )

    assert settings.simulated_data_only is False
    assert settings.data41_open_source_enabled is True
    assert settings.effective_query_engine_mode == "DETERMINISTIC_ONLY"


def test_full_integration_safe_degraded_mode_rejects_shadow_or_enabled_sqlbot():
    for unsafe in (
        {"query_engine_mode": "SHADOW"},
        {"query_engine_mode": "DETERMINISTIC_ONLY", "sqlbot_engine_enabled": True},
        {"query_engine_mode": "DETERMINISTIC_ONLY", "sqlbot_runtime_verified": True},
    ):
        with pytest.raises(ValidationError):
            _preproduction_settings(
                release_version="4.1.0-integration-full.1",
                sqlbot_included_in_v4_release=True,
                sqlbot_provider_eligibility="REGISTERED_NOT_ELIGIBLE",
                **unsafe,
            )


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
