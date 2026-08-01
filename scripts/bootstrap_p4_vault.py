"""Initialize/unseal Vault and provision least-privilege P4 KV v2 references."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import time
from pathlib import Path

import httpx


def request(client: httpx.Client, method: str, path: str, *, token: str | None = None, **kwargs) -> httpx.Response:
    headers = {"X-Vault-Token": token} if token else {}
    return client.request(method, path, headers=headers, **kwargs)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", default="http://vault:8200")
    parser.add_argument("--runtime-dir", type=Path, default=Path("/run/p4-runtime"))
    args = parser.parse_args()
    root = args.runtime_dir
    client = httpx.Client(base_url=args.address, timeout=5)
    for _ in range(60):
        try:
            response = client.get("/v1/sys/health")
            if response.status_code in {200, 429, 472, 473, 501, 503}:
                break
        except httpx.HTTPError:
            pass
        time.sleep(1)
    else:
        raise RuntimeError("Vault did not start")

    initialized = client.get("/v1/sys/init").json().get("initialized", False)
    root_token: str | None = None
    if not initialized:
        result = client.post("/v1/sys/init", json={"secret_shares": 1, "secret_threshold": 1}).json()
        unseal_key = result["keys_base64"][0]
        root_token = result["root_token"]
        (root / "vault_unseal_key").write_text(unseal_key, encoding="utf-8")
        os.chmod(root / "vault_unseal_key", 0o600)
        # Persist only across an interrupted bootstrap. The file is emptied
        # after AppRole provisioning and root-token revocation below.
        (root / "vault_recovery_root").write_text(root_token, encoding="utf-8")
        os.chmod(root / "vault_recovery_root", 0o600)
    else:
        unseal_key = (root / "vault_unseal_key").read_text(encoding="utf-8").strip()
    health = client.get("/v1/sys/health").json()
    if health.get("sealed"):
        client.post("/v1/sys/unseal", json={"key": unseal_key}).raise_for_status()

    role_id_file = root / "vault_role_id"
    secret_id_file = root / "vault_secret_id"
    rotation_role_id_file = root / "vault_rotation_role_id"
    rotation_secret_id_file = root / "vault_rotation_secret_id"
    recovery_root_file = root / "vault_recovery_root"
    if root_token is None and recovery_root_file.exists():
        candidate = recovery_root_file.read_text(encoding="utf-8").strip()
        root_token = candidate or None
    if root_token is None and role_id_file.exists() and secret_id_file.exists():
        auth = client.post("/v1/auth/approle/login", json={
            "role_id": role_id_file.read_text(encoding="utf-8").strip(),
            "secret_id": secret_id_file.read_text(encoding="utf-8").strip(),
        })
        auth.raise_for_status()
        print(json.dumps({"status": "READY", "initialized": True, "unsealed": True, "provider": "VAULT_KV_V2", "secret_values_printed": False}))
        return
    if root_token is None:
        raise RuntimeError(
            "Vault AppRole bootstrap files are unavailable and no staged recovery root exists; "
            "run the reviewed recovery procedure before restarting bootstrap"
        )

    mounts = request(client, "GET", "/v1/sys/mounts", token=root_token).json()
    if "preprod-kv/" not in mounts:
        request(client, "POST", "/v1/sys/mounts/preprod-kv", token=root_token, json={"type": "kv", "options": {"version": "2"}}).raise_for_status()
    auths = request(client, "GET", "/v1/sys/auth", token=root_token).json()
    if "approle/" not in auths:
        request(client, "POST", "/v1/sys/auth/approle", token=root_token, json={"type": "approle"}).raise_for_status()
    audits = request(client, "GET", "/v1/sys/audit", token=root_token).json()
    if "file/" not in audits:
        request(client, "PUT", "/v1/sys/audit/file", token=root_token, json={"type": "file", "options": {"file_path": "/vault/audit/audit.jsonl"}}).raise_for_status()
    policy = """
path "preprod-kv/data/chatbi/*" { capabilities = ["read"] }
path "preprod-kv/metadata/chatbi/*" { capabilities = ["read", "list"] }
path "sys/health" { capabilities = ["read"] }
"""
    request(client, "PUT", "/v1/sys/policies/acl/chatbi-api", token=root_token, json={"policy": policy}).raise_for_status()
    request(client, "POST", "/v1/auth/approle/role/chatbi-api", token=root_token, json={
        "token_policies": ["chatbi-api"], "token_ttl": "10m", "token_max_ttl": "30m",
        "secret_id_ttl": "0", "secret_id_num_uses": 0,
    }).raise_for_status()
    rotation_policy = """
path "preprod-kv/data/chatbi/datasource" { capabilities = ["create", "read", "update"] }
path "preprod-kv/metadata/chatbi/datasource" { capabilities = ["read"] }
path "preprod-kv/data/chatbi/webhook" { capabilities = ["create", "read", "update"] }
path "preprod-kv/metadata/chatbi/webhook" { capabilities = ["read"] }
path "sys/health" { capabilities = ["read"] }
"""
    request(
        client, "PUT", "/v1/sys/policies/acl/chatbi-secret-rotation",
        token=root_token, json={"policy": rotation_policy},
    ).raise_for_status()
    request(client, "POST", "/v1/auth/approle/role/chatbi-secret-rotation", token=root_token, json={
        "token_policies": ["chatbi-secret-rotation"], "token_ttl": "5m", "token_max_ttl": "10m",
        "secret_id_ttl": "0", "secret_id_num_uses": 0,
    }).raise_for_status()

    values = {
        "acceptance": {"value": secrets.token_urlsafe(32)},
        "datasource": {"password": (root / "postgres_password").read_text(encoding="utf-8").strip()},
        "webhook": {"signing_key": secrets.token_urlsafe(48)},
        "sqlbot": {"username": f"p4-{secrets.token_hex(8)}", "password": secrets.token_urlsafe(36)},
    }
    for path, data in values.items():
        response = request(client, "GET", f"/v1/preprod-kv/data/chatbi/{path}", token=root_token)
        if response.status_code == 404:
            request(client, "POST", f"/v1/preprod-kv/data/chatbi/{path}", token=root_token, json={"data": data}).raise_for_status()
        elif not response.is_success:
            response.raise_for_status()
    role_id = request(client, "GET", "/v1/auth/approle/role/chatbi-api/role-id", token=root_token).json()["data"]["role_id"]
    secret_id = request(client, "POST", "/v1/auth/approle/role/chatbi-api/secret-id", token=root_token).json()["data"]["secret_id"]
    rotation_role_id = request(
        client, "GET", "/v1/auth/approle/role/chatbi-secret-rotation/role-id", token=root_token,
    ).json()["data"]["role_id"]
    rotation_secret_id = request(
        client, "POST", "/v1/auth/approle/role/chatbi-secret-rotation/secret-id", token=root_token,
    ).json()["data"]["secret_id"]
    role_id_file.write_text(role_id, encoding="utf-8")
    secret_id_file.write_text(secret_id, encoding="utf-8")
    rotation_role_id_file.write_text(rotation_role_id, encoding="utf-8")
    rotation_secret_id_file.write_text(rotation_secret_id, encoding="utf-8")
    os.chmod(role_id_file, 0o600)
    os.chmod(secret_id_file, 0o600)
    os.chmod(rotation_role_id_file, 0o600)
    os.chmod(rotation_secret_id_file, 0o600)
    request(client, "POST", "/v1/auth/token/revoke-self", token=root_token)
    if recovery_root_file.exists():
        recovery_root_file.write_text("", encoding="utf-8")
        os.chmod(recovery_root_file, 0o600)
    print(json.dumps({
        "status": "READY", "initialized": True, "unsealed": True,
        "provider": "VAULT_KV_V2", "kv_version": 2, "audit_enabled": True,
        "root_token_persisted": False, "secret_values_printed": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
