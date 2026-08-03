import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_health_is_public(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["data_classification"] == "simulated"
    assert response.json()["release_version"] == "0.1.0-dev"
    assert response.headers["x-request-id"].startswith("REQ-")


def test_login_and_me(client, login):
    headers = login()
    response = client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["role"] == "analyst_admin"


def test_invalid_login_is_401(client):
    response = client.post("/api/v1/auth/login", json={"username": "analyst", "password": "wrong-pass"})
    assert response.status_code == 401


def test_missing_token_is_401(client):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_regional_user_is_403_for_admin(client, login):
    headers = login("regional", "AlphaRegion!2026")
    assert client.get("/api/v1/auth/admin-check", headers=headers).status_code == 403


def test_production_configuration_fails_closed():
    with pytest.raises(ValidationError):
        Settings(app_env="production", database_url="sqlite:///bad.db", secret_key="short", auto_bootstrap_demo_users=True)


def test_production_configuration_accepts_private_rc_baseline():
    settings = Settings(
        app_env="production",
        database_url="postgresql+psycopg://renewable:strong-db-password@db:5432/renewable_private",
        redis_url="redis://redis:6379/0",
        secret_key="a-secure-private-release-secret-key",
        auto_bootstrap_demo_users=False,
        public_base_url="https://analytics.example.internal",
        cors_origins="https://analytics.example.internal",
        trusted_hosts="analytics.example.internal",
        release_version="0.6.0-rc1",
        simulated_data_only=True,
    )
    assert settings.app_env == "production"


@pytest.mark.parametrize(
    "override",
    [
        {"sqlbot_engine_enabled": True, "sqlbot_runtime_verified": True, "chatbi_readonly_execution_enabled": True,
         "chatbi_readonly_database_url": "postgresql+psycopg://readonly:strong-password@db:5432/renewable_private"},
        {"sqlbot_runtime_verified": True},
        {"query_engine_mode": "CANARY"},
        {"query_engine_mode": "SQLBOT_ENABLED"},
    ],
)
def test_v4_release_rejects_sqlbot_runtime_configuration(override):
    values = {
        "app_env": "production",
        "database_url": "postgresql+psycopg://renewable:strong-db-password@db:5432/renewable_private",
        "redis_url": "redis://redis:6379/0",
        "secret_key": "a-secure-private-release-secret-key",
        "auto_bootstrap_demo_users": False,
        "public_base_url": "https://analytics.example.internal",
        "cors_origins": "https://analytics.example.internal",
        "trusted_hosts": "analytics.example.internal",
        "release_version": "4.0.0-rc.3",
        "simulated_data_only": True,
        **override,
    }
    with pytest.raises(ValidationError, match="not included in the v4 release"):
        Settings(**values)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("public_base_url", "http://analytics.example.internal"),
        ("cors_origins", "http://analytics.example.internal"),
        ("trusted_hosts", "*"),
        ("release_version", "0.6.0-dev"),
        ("simulated_data_only", False),
        ("database_pool_size", 0),
        ("database_pool_size", 51),
        ("database_max_overflow", -1),
        ("database_max_overflow", 51),
        ("database_pool_timeout_seconds", 0),
        ("database_pool_timeout_seconds", 121),
    ],
)
def test_production_configuration_rejects_unsafe_release_values(field, value):
    values = {
        "app_env": "production",
        "database_url": "postgresql+psycopg://renewable:strong-db-password@db:5432/renewable_private",
        "redis_url": "redis://redis:6379/0",
        "secret_key": "a-secure-private-release-secret-key",
        "auto_bootstrap_demo_users": False,
        "public_base_url": "https://analytics.example.internal",
        "cors_origins": "https://analytics.example.internal",
        "trusted_hosts": "analytics.example.internal",
        "release_version": "0.6.0-rc1",
        "simulated_data_only": True,
    }
    values[field] = value
    with pytest.raises(ValidationError):
        Settings(**values)
