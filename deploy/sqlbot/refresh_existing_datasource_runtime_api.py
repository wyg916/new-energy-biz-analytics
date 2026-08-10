"""Refresh persisted SQLBot datasource table allowlists through official APIs.

The helper deliberately reuses the encrypted connection configuration already
stored by SQLBot.  It never decrypts, logs, or returns datasource credentials.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import httpx


API = os.getenv(
    "SQLBOT_RUNTIME_API_BASE_URL",
    "http://127.0.0.1:8000/api/v1",
).rstrip("/")


@dataclass(frozen=True)
class DatasourceContract:
    name: str
    relations: tuple[str, ...]


CONTRACTS = (
    DatasourceContract(
        "charging_ops",
        (
            "active_context",
            "dim_station",
            "fact_charging_session",
            "fact_device_status_event",
            "fact_energy_cost",
            "fact_operation_expense",
        ),
    ),
    DatasourceContract(
        "sales_ops",
        (
            "active_context",
            "sales_business_date",
            "sales_channel",
            "sales_customer",
            "sales_order",
            "sales_order_item",
            "sales_product",
            "sales_product_category",
            "sales_region",
            "salesperson",
        ),
    ),
)


def _data(response: httpx.Response, operation: str) -> Any:
    if response.status_code >= 400:
        raise RuntimeError(f"{operation} failed with status={response.status_code}")
    payload = response.json()
    return payload.get("data", payload) if isinstance(payload, dict) else payload


def _login(client: httpx.Client) -> dict[str, str]:
    password = os.getenv("DEFAULT_PWD")
    if not password:
        raise RuntimeError("SQLBot admin CredentialReference is unavailable")
    login = _data(
        client.post(
            f"{API}/mcp/mcp_start",
            json={
                "username": os.getenv("SQLBOT_ADMIN_USERNAME", "admin"),
                "password": password,
            },
        ),
        "login",
    )
    password = ""
    token = login.get("access_token") if isinstance(login, dict) else None
    if not isinstance(token, str) or not token:
        raise RuntimeError("SQLBot admin authentication returned no token")
    return {"X-SQLBOT-TOKEN": f"Bearer {token}"}


def _names(items: Any, key: str) -> set[str]:
    if not isinstance(items, list):
        return set()
    return {
        str(item[key])
        for item in items
        if isinstance(item, dict) and item.get(key)
    }


def _refresh(
    client: httpx.Client,
    headers: dict[str, str],
    contract: DatasourceContract,
    listed: list[dict[str, Any]],
) -> dict[str, Any]:
    matches = [item for item in listed if item.get("name") == contract.name]
    if len(matches) != 1 or matches[0].get("id") is None:
        raise RuntimeError(f"{contract.name} persisted datasource cardinality mismatch")
    datasource_id = matches[0]["id"]
    detail = _data(
        client.post(f"{API}/datasource/get/{datasource_id}", headers=headers),
        f"{contract.name} detail",
    )
    if not isinstance(detail, dict) or not detail.get("configuration"):
        raise RuntimeError(f"{contract.name} encrypted configuration is unavailable")
    discovered = _data(
        client.post(
            f"{API}/datasource/getTablesByConf",
            headers=headers,
            json=detail,
            timeout=120,
        ),
        f"{contract.name} discovery",
    )
    discovered_names = _names(discovered, "tableName")
    expected = set(contract.relations)
    if discovered_names != expected:
        raise RuntimeError(
            f"{contract.name} relation contract mismatch: "
            f"expected={len(expected)} discovered={len(discovered_names)}"
        )
    current = _data(
        client.post(
            f"{API}/datasource/tableList/{datasource_id}",
            headers=headers,
        ),
        f"{contract.name} current allowlist",
    )
    comments = {
        str(item.get("table_name")): str(
            item.get("custom_comment")
            or item.get("table_comment")
            or f"{contract.name} approved semantic relation"
        )
        for item in current
        if isinstance(item, dict) and item.get("table_name")
    }
    tables = [
        {
            "table_name": relation,
            "table_comment": comments.get(
                relation, f"{contract.name} approved semantic relation"
            ),
            "custom_comment": comments.get(
                relation, f"{contract.name} approved semantic relation"
            ),
            "checked": True,
        }
        for relation in contract.relations
    ]
    _data(
        client.post(
            f"{API}/datasource/chooseTables/{datasource_id}",
            headers=headers,
            json=tables,
            timeout=120,
        ),
        f"{contract.name} allowlist refresh",
    )
    _data(
        client.get(f"{API}/datasource/check/{datasource_id}", headers=headers),
        f"{contract.name} connection check",
    )
    persisted = _data(
        client.post(
            f"{API}/datasource/tableList/{datasource_id}",
            headers=headers,
        ),
        f"{contract.name} persisted allowlist",
    )
    persisted_names = _names(persisted, "table_name")
    if persisted_names != expected:
        raise RuntimeError(
            f"{contract.name} persisted allowlist mismatch: "
            f"expected={len(expected)} actual={len(persisted_names)}"
        )
    return {
        "name": contract.name,
        "datasource_id": str(datasource_id),
        "relation_count_before": len(_names(current, "table_name")),
        "relation_count_after": len(persisted_names),
        "connection_status": "PASS",
        "configuration_reused_in_memory": True,
        "configuration_value_exposed": False,
    }


def main() -> None:
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        headers = _login(client)
        listed = _data(
            client.get(f"{API}/datasource/list", headers=headers),
            "datasource list",
        )
        if not isinstance(listed, list):
            raise RuntimeError("SQLBot datasource list response is invalid")
        results = [
            _refresh(client, headers, contract, listed)
            for contract in CONTRACTS
        ]
    print(json.dumps({
        "status": "PASS",
        "upstream": "SQLBot v1.10.0",
        "configuration_method": "official_runtime_api",
        "datasources": results,
        "credential_reexposed": False,
        "secret_values_exposed": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
