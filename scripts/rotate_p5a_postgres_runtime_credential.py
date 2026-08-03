"""Rotate the isolated P5A PostgreSQL credential without printing its value."""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

import httpx
import psycopg
from psycopg import sql


RUNTIME = Path("/run/p4-runtime")
KEYCLOAK_RUNTIME = Path("/run/p4-keycloak")


def _replace_secret(path: Path, value: str, mode: int) -> None:
    temporary = path.with_name(f".{path.name}.rotate")
    temporary.write_text(value, encoding="utf-8")
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def _vault_token(client: httpx.Client) -> str:
    response = client.post("/v1/auth/approle/login", json={
        "role_id": (RUNTIME / "vault_rotation_role_id").read_text(encoding="utf-8").strip(),
        "secret_id": (RUNTIME / "vault_rotation_secret_id").read_text(encoding="utf-8").strip(),
    })
    response.raise_for_status()
    return str(response.json()["auth"]["client_token"])


def main() -> None:
    old_password = (RUNTIME / "postgres_password").read_text(encoding="utf-8").strip()
    new_password = secrets.token_urlsafe(48)
    with psycopg.connect(
        host="db", port=5432, dbname="renewable_p5a", user="alpha", password=old_password,
        autocommit=True,
    ) as connection:
        connection.execute(
            sql.SQL("ALTER ROLE {} WITH PASSWORD {}").format(
                sql.Identifier("alpha"), sql.Literal(new_password),
            )
        )
    _replace_secret(RUNTIME / "postgres_password", new_password, 0o600)
    _replace_secret(KEYCLOAK_RUNTIME / "postgres_password", new_password, 0o640)
    with httpx.Client(base_url="http://vault:8200", timeout=10) as client:
        token = _vault_token(client)
        response = client.post(
            "/v1/preprod-kv/data/chatbi/datasource",
            headers={"X-Vault-Token": token},
            json={"data": {"password": new_password}},
        )
        response.raise_for_status()
        vault_version = int(response.json()["data"]["version"])
    print(json.dumps({
        "status": "PASS",
        "database_role_rotated": True,
        "runtime_file_rotated": True,
        "keycloak_runtime_file_rotated": True,
        "vault_datasource_version": vault_version,
        "secret_value_printed": False,
        "repository_secret_written": False,
    }, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({
            "status": "FAIL",
            "error_type": type(exc).__name__,
            "secret_value_printed": False,
        }, sort_keys=True))
        raise SystemExit(1) from None
