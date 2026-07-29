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
    api_source_allowlist: str = "localhost,127.0.0.1,host.docker.internal"
    public_base_url: str = "http://localhost:8080"
    trusted_hosts: str = "localhost,127.0.0.1,testserver"
    release_version: str = "0.1.0-dev"
    expected_database_revision: str = "0006"

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
