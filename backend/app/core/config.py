from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "新能源企业经营分析智能平台"
    app_env: Literal["development", "test", "production"] = "development"
    debug: bool = False
    secret_key: str = "local-alpha-change-me"
    access_token_minutes: int = 60
    database_url: str = "sqlite:///./data/alpha.db"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: str = "http://localhost:5173,http://localhost:8080"
    auto_bootstrap_demo_users: bool = True
    simulated_data_only: bool = True
    data_import_root: str = "data/imports"
    knowledge_source_root: str = "/app/knowledge_sources"
    api_source_allowlist: str = "localhost,127.0.0.1,host.docker.internal"
    public_base_url: str = "http://localhost:8080"
    trusted_hosts: str = "localhost,127.0.0.1,testserver"
    release_version: str = "0.1.0-dev"
    expected_database_revision: str = "p2b_0001"
    platform_version_routing_enabled: bool | None = None
    sqlbot_engine_enabled: bool = False
    sqlbot_runtime_verified: bool = False
    sqlbot_base_url: str = "http://sqlbot:8000/api/v1"
    sqlbot_username_env_key: str = "SQLBOT_SERVICE_USERNAME"
    sqlbot_password_env_key: str = "SQLBOT_SERVICE_PASSWORD"
    sqlbot_timeout_seconds: float = 20.0
    sqlbot_circuit_failure_threshold: int = 3
    sqlbot_circuit_recovery_seconds: int = 30
    query_engine_mode: Literal[
        "DETERMINISTIC_ONLY",
        "SHADOW",
        "CANARY",
        "SQLBOT_ENABLED",
        "DISABLED",
    ] | None = None
    query_engine_feature_flag_version: str = "p1b-1"
    query_engine_canary_percentage: float = 5.0
    query_engine_canary_tenants: str = ""
    query_engine_canary_workspaces: str = ""
    query_engine_canary_users: str = ""
    query_engine_canary_scenarios: str = "charging_ops,sales_ops"
    chatbi_readonly_execution_enabled: bool = False
    chatbi_readonly_database_url: str | None = None
    chatbi_statement_timeout_ms: int = 5000
    model_gateway_kimi_base_url: str = ""
    model_gateway_kimi_model_name: str = ""
    model_gateway_kimi_credential_ref: str = "env://MODEL_GATEWAY_KIMI_API_KEY"
    model_gateway_kimi_enabled: bool = False
    model_gateway_mimo_base_url: str = ""
    model_gateway_mimo_model_name: str = ""
    model_gateway_mimo_credential_ref: str = "env://MODEL_GATEWAY_MIMO_API_KEY"
    model_gateway_mimo_enabled: bool = False
    model_gateway_deepseek_base_url: str = ""
    model_gateway_deepseek_model_name: str = ""
    model_gateway_deepseek_credential_ref: str = "env://MODEL_GATEWAY_DEEPSEEK_API_KEY"
    model_gateway_deepseek_enabled: bool = False
    platform_tenant_id: str = "tenant-alpha"
    platform_org_id: str = "org-alpha"
    platform_workspace_id: str = "workspace-alpha"

    @model_validator(mode="after")
    def fail_closed_in_production(self) -> "Settings":
        if self.app_env == "production":
            failures = []
            if self.secret_key == "local-alpha-change-me" or len(self.secret_key) < 32:
                failures.append("SECRET_KEY must be non-default and at least 32 characters")
            if self.debug:
                failures.append("DEBUG must be false")
            if self.auto_bootstrap_demo_users:
                failures.append("AUTO_BOOTSTRAP_DEMO_USERS must be false")
            if not self.database_url.startswith("postgresql"):
                failures.append("DATABASE_URL must use PostgreSQL")
            else:
                parsed_database = urlparse(self.database_url.replace("postgresql+psycopg", "postgresql", 1))
                if not parsed_database.password or parsed_database.password in {"alpha-local-only", "change-me"}:
                    failures.append("DATABASE_URL must contain a non-default password")
            if not self.redis_url.startswith("redis://"):
                failures.append("REDIS_URL must use Redis")
            if not self.public_base_url.startswith("https://"):
                failures.append("PUBLIC_BASE_URL must use HTTPS")
            if any(not origin.startswith("https://") for origin in self.cors_origin_list):
                failures.append("CORS_ORIGINS must contain HTTPS origins only")
            public_host = urlparse(self.public_base_url).hostname
            if not public_host or public_host not in self.trusted_host_list:
                failures.append("TRUSTED_HOSTS must contain the PUBLIC_BASE_URL host")
            if "*" in self.trusted_host_list:
                failures.append("TRUSTED_HOSTS must not contain wildcard hosts")
            if self.release_version.endswith("-dev"):
                failures.append("RELEASE_VERSION must identify a release candidate or release")
            if not self.simulated_data_only:
                failures.append("SIMULATED_DATA_ONLY must remain true for this release candidate")
            if self.chatbi_readonly_execution_enabled and (
                not self.chatbi_readonly_database_url
                or not self.chatbi_readonly_database_url.startswith("postgresql")
            ):
                failures.append(
                    "CHATBI_READONLY_DATABASE_URL must use PostgreSQL when the independent readonly boundary is enabled"
                )
            if self.sqlbot_engine_enabled:
                if not self.sqlbot_runtime_verified:
                    failures.append(
                        "SQLBOT_RUNTIME_VERIFIED must be true before enabling SQLBot in production"
                    )
                if not self.chatbi_readonly_execution_enabled:
                    failures.append(
                        "CHATBI_READONLY_EXECUTION_ENABLED must be true before enabling SQLBot in production"
                    )
            if self.effective_query_engine_mode != "DETERMINISTIC_ONLY":
                failures.append(
                    "production QUERY_ENGINE_MODE must be DETERMINISTIC_ONLY"
                )
            if self.effective_platform_version_routing_enabled:
                failures.append(
                    "production PLATFORM_VERSION_ROUTING_ENABLED must be false"
                )
            if failures:
                raise ValueError("production configuration rejected: " + "; ".join(failures))
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    def ensure_local_directories(self) -> None:
        if self.database_url.startswith("sqlite"):
            Path("data").mkdir(parents=True, exist_ok=True)
        Path(self.data_import_root).mkdir(parents=True, exist_ok=True)

    @property
    def api_source_allowed_hosts(self) -> set[str]:
        return {item.strip().lower() for item in self.api_source_allowlist.split(",") if item.strip()}

    @property
    def trusted_host_list(self) -> list[str]:
        return [item.strip().lower() for item in self.trusted_hosts.split(",") if item.strip()]

    @property
    def effective_query_engine_mode(self) -> str:
        if self.query_engine_mode:
            return self.query_engine_mode
        return "DETERMINISTIC_ONLY" if self.app_env == "production" else "SHADOW"

    @property
    def effective_platform_version_routing_enabled(self) -> bool:
        if self.platform_version_routing_enabled is not None:
            return self.platform_version_routing_enabled
        return self.app_env != "production"

    @staticmethod
    def _csv_set(value: str) -> frozenset[str]:
        return frozenset(item.strip() for item in value.split(",") if item.strip())

    @property
    def query_engine_canary_scope(self) -> dict[str, frozenset[str]]:
        return {
            "tenants": self._csv_set(self.query_engine_canary_tenants),
            "workspaces": self._csv_set(self.query_engine_canary_workspaces),
            "users": self._csv_set(self.query_engine_canary_users),
            "scenarios": self._csv_set(self.query_engine_canary_scenarios),
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
