from __future__ import annotations

import json
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.security import create_access_token
from app.core.config import Settings
import app.governance.identity as identity_module
from app.governance.identity import IdentityResolutionError, RemoteJWKSOIDCProvider
from app.governance.secrets import SecretResolutionError, VaultKVv2SecretProvider
from app.preproduction.oidc import OIDCFlowError, OIDCSessionStore


def secure_settings(**overrides) -> Settings:
    values = {
        "app_env": "preproduction",
        "secret_key": "s" * 48,
        "database_url": "postgresql+psycopg://alpha:non-default-password@db/renewable_p4",
        "redis_url": "redis://:non-default-password@redis:6379/0",
        "cors_origins": "https://p4.localhost:8444",
        "public_base_url": "https://p4.localhost:8444",
        "trusted_hosts": "p4.localhost",
        "auto_bootstrap_demo_users": False,
        "release_version": "4.0.0-rc.1",
        "expected_database_revision": "p4_0001",
        "local_auth_enabled": False,
        "query_engine_mode": "SHADOW",
        "sqlbot_engine_enabled": False,
        "production_release_authorized": False,
        "oidc_enabled": True,
        "oidc_issuer": "https://p4.localhost:8444/oidc/realms/chatbi",
        "oidc_internal_base_url": "http://oidc:8080/oidc/realms/chatbi",
        "oidc_redirect_uri": "https://p4.localhost:8444/oidc/callback",
        "vault_enabled": True,
    }
    values.update(overrides)
    return Settings(**values)


def test_preproduction_settings_fail_closed() -> None:
    assert secure_settings().production_release_authorized is False
    with pytest.raises(ValueError, match="LOCAL_AUTH_ENABLED"):
        secure_settings(local_auth_enabled=True)
    with pytest.raises(ValueError, match="QUERY_ENGINE_MODE"):
        secure_settings(query_engine_mode="CANARY")
    with pytest.raises(ValueError, match="Vault"):
        secure_settings(vault_enabled=False)


def test_preproduction_rejects_an_existing_local_bearer(client, monkeypatch) -> None:
    from app.bootstrap import bootstrap_demo_users
    from app.core.database import SessionLocal
    from app.models.auth import User
    from sqlalchemy import select

    bootstrap_demo_users()
    with SessionLocal() as db:
        analyst = db.scalar(select(User).where(User.username == "analyst"))
        token = create_access_token(analyst.id, analyst.role)
    monkeypatch.setattr(identity_module, "get_settings", lambda: secure_settings())
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_remote_jwks_verifies_signature_claims_and_nonce(monkeypatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    jwk["kid"] = "p4-key"
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: httpx.Response(
        200, json={"keys": [jwk]}, request=httpx.Request("GET", "http://oidc/certs")
    ))
    provider = RemoteJWKSOIDCProvider(
        issuer="https://issuer.example/realms/chatbi", audience="chatbi-web",
        jwks_url="http://oidc/certs", provider_code="OIDC_PREPROD",
    )
    now = int(time.time())
    claims = {
        "iss": "https://issuer.example/realms/chatbi", "aud": "chatbi-web",
        "sub": "subject-1", "iat": now, "exp": now + 300, "nonce": "nonce-1",
        "tenant_id": "tenant-alpha", "workspace_id": "workspace-alpha",
        "groups": ["analysts"],
    }
    token = jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "p4-key"})
    verified = provider.verify_with_nonce(token, expected_nonce="nonce-1")
    assert verified.subject == "subject-1"
    assert verified.groups == ("analysts",)
    with pytest.raises(IdentityResolutionError, match="nonce"):
        provider.verify_with_nonce(token, expected_nonce="wrong")
    wrong_audience = jwt.encode({**claims, "aud": "other"}, private_key, algorithm="RS256", headers={"kid": "p4-key"})
    with pytest.raises(IdentityResolutionError) as exc:
        provider.verify(wrong_audience)
    assert exc.value.code == "OIDC_AUDIENCE_MISMATCH"


class FakeRedis:
    def __init__(self) -> None:
        self.values = {}

    def setex(self, key, ttl, value):
        self.values[key] = value

    def getdel(self, key):
        return self.values.pop(key, None)

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        self.values.pop(key, None)

    def ping(self):
        return True


def test_oidc_state_is_one_time_and_session_is_revocable() -> None:
    store = OIDCSessionStore(FakeRedis(), settings=secure_settings())
    transaction = store.create_transaction("https://p4.localhost:8444/oidc/callback")
    assert store.consume_transaction(transaction.state).nonce == transaction.nonce
    with pytest.raises(OIDCFlowError) as exc:
        store.consume_transaction(transaction.state)
    assert exc.value.code == "OIDC_STATE_INVALID"
    session_id = store.create_session(principal_id="PRN-1", user_id=1, groups=("analysts",), refresh_token="not-returned")
    assert store.get_session(session_id)["principal_id"] == "PRN-1"
    store.revoke_session(session_id)
    with pytest.raises(OIDCFlowError):
        store.get_session(session_id)


def test_vault_kv_v2_version_cache_invalidation_and_fail_closed(tmp_path) -> None:
    role_file = tmp_path / "role"
    secret_file = tmp_path / "secret"
    role_file.write_text("role-id", encoding="utf-8")
    secret_file.write_text("secret-id", encoding="utf-8")
    calls = {"login": 0, "read": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/approle/login"):
            calls["login"] += 1
            return httpx.Response(200, json={"auth": {"client_token": "vault-token", "lease_duration": 300}})
        if request.url.path.endswith("/preprod-kv/data/chatbi/datasource"):
            calls["read"] += 1
            assert request.url.params["version"] == "1"
            assert request.headers["X-Vault-Token"] == "vault-token"
            return httpx.Response(200, json={"data": {"data": {"password": "resolved-only-in-memory"}}})
        return httpx.Response(503)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = VaultKVv2SecretProvider(
        address="http://vault:8200", role_id_file=str(role_file), secret_id_file=str(secret_file),
        cache_ttl_seconds=60, client=client,
    )
    identifier = "preprod-kv/chatbi/datasource#password@1"
    assert provider.resolve(identifier) == "resolved-only-in-memory"
    assert provider.resolve(identifier) == "resolved-only-in-memory"
    assert calls == {"login": 1, "read": 1}
    provider.invalidate(identifier)
    assert provider.resolve(identifier) == "resolved-only-in-memory"
    assert calls["read"] == 2
    with pytest.raises(SecretResolutionError):
        provider.resolve("preprod-kv/../escape#password@1")
