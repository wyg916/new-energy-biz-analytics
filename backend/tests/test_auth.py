import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_health_is_public(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["data_classification"] == "simulated"


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
