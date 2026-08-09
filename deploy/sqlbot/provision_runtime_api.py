"""Provision SQLBot v1.8.0 local-acceptance datasources through its API.

Run this script inside the pinned SQLBot container. All credentials are read
from runtime environment references. The script never prints tokens,
passwords, datasource configuration ciphertext, or model responses.
"""

from __future__ import annotations

import json
import os
import base64
import binascii
from dataclasses import dataclass
from typing import Any, Callable

import httpx


API_BASE_URL = os.getenv(
    "SQLBOT_RUNTIME_API_BASE_URL",
    "http://127.0.0.1:8000/api/v1",
).rstrip("/")


@dataclass(frozen=True)
class DatasourceSpec:
    name: str
    schema: str
    role_env: str
    password_env: str
    approved_relations: tuple[str, ...]


DATASOURCES = (
    DatasourceSpec(
        name="charging_ops",
        schema="semantic_sqlbot_charging",
        role_env="SQLBOT_READONLY_CHARGING_ROLE",
        password_env="SQLBOT_READONLY_CHARGING_PASSWORD",
        approved_relations=(
            "active_context",
            "dim_station",
            "fact_charging_session",
        ),
    ),
    DatasourceSpec(
        name="sales_ops",
        schema="semantic_sqlbot_sales",
        role_env="SQLBOT_READONLY_SALES_ROLE",
        password_env="SQLBOT_READONLY_SALES_PASSWORD",
        approved_relations=(
            "active_context",
            "sales_channel",
            "sales_order",
            "sales_order_item",
            "sales_product",
            "sales_region",
        ),
    ),
)


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"required CredentialReference env://{name} is unavailable")
    return value


def _response_data(response: httpx.Response, operation: str) -> Any:
    if response.status_code >= 400:
        raise RuntimeError(
            f"{operation} failed with sanitized status={response.status_code}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"{operation} returned non-JSON data") from exc
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def _login(client: httpx.Client, password: str) -> str | None:
    response = client.post(
        f"{API_BASE_URL}/mcp/mcp_start",
        json={
            "username": os.getenv("SQLBOT_ADMIN_USERNAME", "admin"),
            "password": password,
        },
    )
    if response.status_code >= 400:
        return None
    data = _response_data(response, "SQLBot login")
    if not isinstance(data, dict):
        return None
    token = data.get("access_token")
    return token if isinstance(token, str) and token else None


def _admin_headers(client: httpx.Client) -> tuple[dict[str, str], bool]:
    runtime_password = _required("DEFAULT_PWD")
    token = _login(client, runtime_password)
    rotated = False
    if token is None:
        if os.getenv("SQLBOT_ALLOW_LOCAL_DEFAULT_BOOTSTRAP", "").lower() != "true":
            raise RuntimeError(
                "SQLBot admin runtime credential does not match the persisted "
                "local-acceptance account"
            )
        # SQLBot v1.8.0 seeds a public image default before applying the
        # runtime DEFAULT_PWD. Resolve that default from the pinned runtime
        # class without copying, logging, or returning it, then immediately
        # rotate the account to the runtime credential through the official API.
        from common.core.config import Settings

        image_default = Settings.model_fields["DEFAULT_PWD"].default
        if not isinstance(image_default, str) or not image_default:
            raise RuntimeError("SQLBot image bootstrap credential is unavailable")
        token = _login(client, image_default)
        image_default = ""
        if token is None:
            raise RuntimeError("SQLBot local bootstrap authentication failed")
        bootstrap_headers = {"X-SQLBOT-TOKEN": f"Bearer {token}"}
        _response_data(
            client.patch(
                f"{API_BASE_URL}/user/pwd/1",
                headers=bootstrap_headers,
            ),
            "SQLBot admin runtime credential rotation",
        )
        token = _login(client, runtime_password)
        if token is None:
            raise RuntimeError("SQLBot admin credential rotation was not recoverable")
        rotated = True
    return {"X-SQLBOT-TOKEN": f"Bearer {token}"}, rotated


def _configuration(
    spec: DatasourceSpec,
    encrypt: Callable[[str], bytes | str],
) -> str:
    raw = json.dumps(
        {
            "host": _required("SQLBOT_READONLY_DB_HOST"),
            "port": int(os.getenv("SQLBOT_READONLY_DB_PORT", "5432")),
            "username": _required(spec.role_env),
            "password": _required(spec.password_env),
            "database": os.getenv(
                "SQLBOT_READONLY_DB_NAME",
                "renewable_alpha",
            ),
            "driver": "org.postgresql.Driver",
            "extraJdbc": "",
            "dbSchema": spec.schema,
            "filename": "",
            "sheets": [],
            "mode": "",
            "timeout": 10,
            "lowVersion": False,
            "ssl": False,
        },
        separators=(",", ":"),
    )
    encrypted = encrypt(raw)
    if isinstance(encrypted, bytes):
        encrypted = encrypted.decode()
    return encrypted


def _upsert_datasource(
    client: httpx.Client,
    headers: dict[str, str],
    spec: DatasourceSpec,
    encrypt: Callable[[str], bytes | str],
) -> dict[str, Any]:
    configuration = _configuration(spec, encrypt)
    candidate = {
        "name": spec.name,
        "description": (
            f"{spec.name} approved semantic views; fixed-seed simulated data"
        ),
        "type": "pg",
        "configuration": configuration,
        "status": "Success",
        "num": "",
        "oid": 1,
        "tables": [],
        "recommended_config": 0,
    }
    _response_data(
        client.post(
            f"{API_BASE_URL}/datasource/check",
            headers=headers,
            json=candidate,
        ),
        f"{spec.name} connection check",
    )
    discovered = _response_data(
        client.post(
            f"{API_BASE_URL}/datasource/getTablesByConf",
            headers=headers,
            json={
                "id": 0,
                "name": spec.name,
                "description": candidate["description"],
                "type": "pg",
                "type_name": "PostgreSQL",
                "configuration": configuration,
                "create_by": 1,
                "status": "Success",
                "num": "",
                "oid": 1,
                "recommended_config": 0,
            },
        ),
        f"{spec.name} table discovery",
    )
    discovered_names = {
        str(item.get("tableName"))
        for item in discovered
        if isinstance(item, dict) and item.get("tableName")
    }
    if discovered_names != set(spec.approved_relations):
        raise RuntimeError(
            f"{spec.name} relation contract mismatch: "
            f"expected={len(spec.approved_relations)} "
            f"discovered={len(discovered_names)}"
        )
    candidate["tables"] = [
        {
            "table_name": relation,
            "table_comment": f"{spec.name} approved semantic relation",
            "custom_comment": f"{spec.name} approved semantic relation",
            "checked": True,
        }
        for relation in spec.approved_relations
    ]

    existing = _response_data(
        client.get(f"{API_BASE_URL}/datasource/list", headers=headers),
        "SQLBot datasource list",
    )
    current = next(
        (
            item
            for item in existing
            if isinstance(item, dict) and item.get("name") == spec.name
        ),
        None,
    )
    if current is None:
        saved = _response_data(
            client.post(
                f"{API_BASE_URL}/datasource/add",
                headers=headers,
                json=candidate,
                timeout=120,
            ),
            f"{spec.name} datasource create",
        )
        datasource_id = saved.get("id") if isinstance(saved, dict) else None
        operation = "created"
    else:
        datasource_id = current.get("id")
        if datasource_id is None:
            raise RuntimeError(f"{spec.name} datasource id is unavailable")
        # A recovered acceptance runtime can retain a valid catalogue whose
        # encrypted connection still points at an obsolete database host.
        # Reusing that row without updating it makes the connection check test
        # stale state rather than the current DATA-4.1 PostgreSQL service.
        candidate["id"] = datasource_id
        _response_data(
            client.post(
                f"{API_BASE_URL}/datasource/update",
                headers=headers,
                json=candidate,
                timeout=120,
            ),
            f"{spec.name} datasource update",
        )
        _response_data(
            client.post(
                f"{API_BASE_URL}/datasource/chooseTables/{datasource_id}",
                headers=headers,
                json=candidate["tables"],
                timeout=120,
            ),
            f"{spec.name} datasource table allowlist update",
        )
        operation = "updated"
    if datasource_id is None:
        raise RuntimeError(f"{spec.name} datasource id is unavailable")
    _response_data(
        client.get(
            f"{API_BASE_URL}/datasource/check/{datasource_id}",
            headers=headers,
        ),
        f"{spec.name} persisted connection check",
    )
    tables = _response_data(
        client.post(
            f"{API_BASE_URL}/datasource/tableList/{datasource_id}",
            headers=headers,
        ),
        f"{spec.name} persisted table list",
    )
    persisted_names = {
        str(item.get("table_name"))
        for item in tables
        if isinstance(item, dict) and item.get("table_name")
    }
    if persisted_names != set(spec.approved_relations):
        raise RuntimeError(
            f"{spec.name} persisted allowlist mismatch: "
            f"expected={len(spec.approved_relations)} "
            f"actual={len(persisted_names)}"
        )
    preview_relation = (
        "fact_charging_session"
        if spec.name == "charging_ops"
        else "sales_order"
    )
    preview_table = next(
        (
            item
            for item in tables
            if isinstance(item, dict)
            and item.get("table_name") == preview_relation
        ),
        None,
    )
    if preview_table is None:
        raise RuntimeError(f"{spec.name} preview relation is unavailable")
    preview = _response_data(
        client.post(
            f"{API_BASE_URL}/datasource/previewData/{datasource_id}",
            headers=headers,
            json={"table": preview_table, "fields": []},
        ),
        f"{spec.name} data preview",
    )
    preview_rows = (
        preview.get("data")
        if isinstance(preview, dict) and isinstance(preview.get("data"), list)
        else []
    )
    preview_sql = preview.get("sql") if isinstance(preview, dict) else None
    if not preview_rows or not isinstance(preview_sql, str):
        raise RuntimeError(f"{spec.name} data preview returned no auditable result")
    import sqlglot
    from sqlglot import exp

    sql_candidates = [preview_sql]
    try:
        decoded_sql = base64.b64decode(
            preview_sql,
            validate=True,
        ).decode("utf-8")
        sql_candidates.insert(0, decoded_sql)
    except (binascii.Error, ValueError, UnicodeDecodeError):
        pass
    statements = None
    for sql_candidate in sql_candidates:
        try:
            statements = sqlglot.parse(sql_candidate, read="postgres")
            break
        except sqlglot.errors.ParseError:
            continue
    if statements is None:
        raise RuntimeError(f"{spec.name} data preview SQL is not parseable")
    preview_select_only = (
        len(statements) == 1
        and statements[0].find(exp.Select) is not None
        and not any(
            statements[0].find(forbidden) is not None
            for forbidden in (
                exp.Insert,
                exp.Update,
                exp.Delete,
                exp.Create,
                exp.Drop,
                exp.Alter,
                exp.Command,
            )
        )
    )
    if not preview_select_only:
        raise RuntimeError(f"{spec.name} data preview SQL is not read-only")
    return {
        "name": spec.name,
        "datasource_id": str(datasource_id),
        "operation": operation,
        "schema": spec.schema,
        "relation_count": len(persisted_names),
        "connection_status": "PASS",
        "preview_relation": preview_relation,
        "preview_row_count": len(preview_rows),
        "preview_select_only": preview_select_only,
        "data_classification": "simulated",
        "credential_value_exposed": False,
    }


def main() -> None:
    # This helper is intentionally coupled to the pinned container at runtime,
    # not to a copied SQLBot source tree in the platform repository.
    from apps.datasource.utils.utils import aes_encrypt

    with httpx.Client(timeout=30, follow_redirects=False) as client:
        headers, rotated = _admin_headers(client)
        results = [
            _upsert_datasource(client, headers, spec, aes_encrypt)
            for spec in DATASOURCES
        ]
    print(json.dumps({
        "upstream": "SQLBot v1.8.0",
        "configuration_method": "official_runtime_api",
        "admin_runtime_credential_rotated": rotated,
        "datasources": results,
        "secret_values_exposed": False,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
