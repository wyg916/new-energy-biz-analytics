"""Synchronize SQLBot's runtime account to governed CredentialReferences."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import select

from app.core.database import SessionLocal
from app.governance.secrets import CredentialReferenceService
from app.models.auth import User
from app.platform.identity import IdentityContextFactory
from app.query_engines.sqlbot.credentials import derive_runtime_account_password


def _login(client: httpx.Client, username: str, password: str) -> str | None:
    response = client.post(
        "mcp/mcp_start",
        json={"username": username, "password": password},
    )
    if response.status_code >= 400:
        return None
    payload = response.json()
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    token = data.get("access_token") if isinstance(data, dict) else None
    return token if isinstance(token, str) and token else None


def _data(response: httpx.Response) -> dict:
    payload = response.json()
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def _find_user_id(
    client: httpx.Client,
    *,
    token: str,
    username: str,
) -> int | None:
    response = client.get(
        "user/pager/1/100",
        headers={"X-SQLBOT-TOKEN": f"Bearer {token}"},
        params={"keyword": username},
    )
    if response.status_code >= 400:
        raise RuntimeError(f"SQLBot account lookup failed status={response.status_code}")
    data = _data(response)
    items = data.get("items")
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and item.get("account") == username:
            user_id = item.get("id")
            return int(user_id) if user_id is not None else None
    return None


def _ensure_target_account(
    client: httpx.Client,
    *,
    token: str,
    username: str,
) -> str:
    user_id = _find_user_id(client, token=token, username=username)
    headers = {"X-SQLBOT-TOKEN": f"Bearer {token}"}
    if user_id is not None:
        response = client.patch(f"user/pwd/{user_id}", headers=headers)
        if response.status_code >= 400:
            raise RuntimeError(
                f"SQLBot service account reset failed status={response.status_code}"
            )
        return "reset"

    info_response = client.get("user/info", headers=headers)
    if info_response.status_code >= 400:
        raise RuntimeError(
            f"SQLBot bootstrap account lookup failed status={info_response.status_code}"
        )
    info = _data(info_response)
    oid = int(info.get("oid") or 0)
    response = client.post(
        "user",
        headers=headers,
        json={
            "account": username,
            "oid": oid,
            "name": "Platform SQLBot Runtime",
            "email": "sqlbot-runtime@local.invalid",
            "status": 1,
            "origin": 0,
            "oid_list": [oid] if oid else [],
            "system_variables": [],
        },
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"SQLBot service account creation failed status={response.status_code}"
        )
    return "created"


def synchronize(
    client: httpx.Client,
    *,
    username: str,
    target_password: str,
    bootstrap_password: str,
    bootstrap_username: str = "admin",
) -> str:
    target_password = derive_runtime_account_password(target_password)
    if _login(client, username, target_password):
        return "already_synchronized"
    token = _login(client, bootstrap_username, bootstrap_password)
    if token is None:
        raise RuntimeError("CredentialReference is stale and bootstrap account cannot authenticate")
    account_operation = "existing"
    if username != bootstrap_username:
        account_operation = _ensure_target_account(
            client,
            token=token,
            username=username,
        )
        token = _login(client, username, bootstrap_password)
        if token is None:
            raise RuntimeError("SQLBot service account bootstrap authentication failed")
    response = client.put(
        "user/pwd",
        headers={"X-SQLBOT-TOKEN": f"Bearer {token}"},
        json={"pwd": bootstrap_password, "new_pwd": target_password},
    )
    if response.status_code >= 400:
        raise RuntimeError(f"SQLBot credential rotation failed status={response.status_code}")
    if _login(client, username, target_password) is None:
        raise RuntimeError("CredentialReference authentication failed after rotation")
    return f"{account_operation}_and_rotated"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlbot-base-url", required=True)
    parser.add_argument("--bootstrap-username", default="admin")
    parser.add_argument("--username-reference-name", default="preprod-sqlbot-username")
    parser.add_argument("--password-reference-name", default="preprod-sqlbot-password")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    bootstrap_password = os.getenv("SQLBOT_BOOTSTRAP_CURRENT_PASSWORD")
    if not bootstrap_password:
        raise RuntimeError("migration-only SQLBot bootstrap credential is unavailable")
    with SessionLocal() as db:
        user = db.scalars(
            select(User)
            .where(User.is_active.is_(True))
            .order_by((User.role == "analyst_admin").desc(), User.id)
        ).first()
        if user is None:
            raise RuntimeError("no authorized platform identity is available")
        service = CredentialReferenceService(db, IdentityContextFactory.from_user(user))
        username_ref = service.active_by_name(args.username_reference_name)
        password_ref = service.active_by_name(args.password_reference_name)
        trace_id = f"SQLBOT-41C-CREDENTIAL-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%f')}"
        username_secret = service.resolve(
            username_ref.credential_ref_id,
            action="sqlbot.authenticate",
            trace_id=trace_id,
        )
        password_secret = service.resolve(
            password_ref.credential_ref_id,
            action="sqlbot.authenticate",
            trace_id=trace_id,
        )
        with httpx.Client(
            base_url=f"{args.sqlbot_base_url.rstrip('/')}/",
            timeout=30,
            follow_redirects=False,
        ) as client:
            operation = synchronize(
                client,
                username=username_secret.value,
                target_password=password_secret.value,
                bootstrap_password=bootstrap_password,
                bootstrap_username=args.bootstrap_username,
            )
    report = {
        "status": "PASS",
        "operation": operation,
        "credential_source": "CREDENTIAL_REFERENCE",
        "username_version": username_secret.version,
        "password_version": password_secret.version,
        "rotation_supported": True,
        "credential_material_adapter": "HMAC_SHA256_SQLBOT_POLICY_V1",
        "env_fallback_enabled": False,
        "secret_values_exposed": False,
    }
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
