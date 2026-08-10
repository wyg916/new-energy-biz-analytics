"""Tune and select an already persisted SQLBot provider through official APIs."""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

import httpx


API = os.getenv(
    "SQLBOT_RUNTIME_API_BASE_URL",
    "http://127.0.0.1:8000/api/v1",
).rstrip("/")
ACCEPTED = {
    "deepseek-v4-flash": "https://api.deepseek.com",
    "kimi-k2.6": "https://api.moonshot.cn/v1",
}
TUNED_CONFIG = [
    {"key": "temperature", "val": 0, "name": "temperature"},
    {
        "key": "extra_body",
        "val": {"thinking": {"type": "disabled"}},
        "name": "extra_body",
    },
    {"key": "max_tokens", "val": 768, "name": "max_tokens"},
    {"key": "max_retries", "val": 0, "name": "max_retries"},
    {"key": "timeout", "val": 12, "name": "timeout"},
]


def _data(response: httpx.Response, operation: str) -> Any:
    if response.status_code >= 400:
        raise RuntimeError(f"{operation} failed with status={response.status_code}")
    payload = response.json()
    return payload.get("data", payload) if isinstance(payload, dict) else payload


def _sanitized_config(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    return [
        {"key": item.get("key"), "val": item.get("val")}
        for item in value
        if isinstance(item, dict) and item.get("key")
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-model", choices=tuple(ACCEPTED), required=True)
    parser.add_argument("--target-id")
    args = parser.parse_args()
    password = os.getenv("DEFAULT_PWD")
    if not password:
        raise RuntimeError("SQLBot admin CredentialReference is unavailable")

    with httpx.Client(timeout=30, follow_redirects=False) as client:
        login = _data(client.post(
            f"{API}/mcp/mcp_start",
            json={
                "username": os.getenv("SQLBOT_ADMIN_USERNAME", "admin"),
                "password": password,
            },
        ), "login")
        token = login.get("access_token") if isinstance(login, dict) else None
        if not isinstance(token, str) or not token:
            raise RuntimeError("SQLBot admin authentication returned no token")
        headers = {"X-SQLBOT-TOKEN": f"Bearer {token}"}
        listed = _data(
            client.get(f"{API}/system/aimodel", headers=headers),
            "model list",
        )
        if not isinstance(listed, list):
            raise RuntimeError("SQLBot model list response is invalid")
        details = []
        for item in listed:
            if not isinstance(item, dict) or item.get("id") is None:
                continue
            detail = _data(
                client.get(
                    f"{API}/system/aimodel/{item['id']}", headers=headers
                ),
                "model detail",
            )
            if isinstance(detail, dict):
                details.append(detail)
        defaults = [item for item in details if item.get("default_model") is True]
        if len(defaults) != 1:
            raise RuntimeError("SQLBot default model cardinality mismatch")
        previous = defaults[0]
        candidates = [
            item for item in details
            if item.get("base_model") == args.target_model
            and item.get("api_domain") == ACCEPTED[args.target_model]
            and (args.target_id is None or str(item.get("id")) == args.target_id)
        ]
        if args.target_id is None and previous.get("base_model") == args.target_model:
            candidates = [previous]
        if len(candidates) != 1:
            raise RuntimeError("accepted target model cardinality mismatch")
        selected = candidates[0]
        api_key = selected.get("api_key")
        if not isinstance(api_key, str) or not api_key:
            raise RuntimeError("persisted provider CredentialReference is unavailable")
        before = _sanitized_config(
            selected.get("config") or selected.get("config_list")
        )
        editor = {
            "id": str(selected["id"]),
            "name": selected["name"],
            "model_type": selected["model_type"],
            "base_model": selected["base_model"],
            "supplier": selected["supplier"],
            "protocol": selected["protocol"],
            "default_model": False,
            "api_domain": selected["api_domain"],
            "api_key": api_key,
            "config_list": TUNED_CONFIG,
        }
        _data(
            client.put(f"{API}/system/aimodel", headers=headers, json=editor),
            "model update",
        )
        _data(
            client.put(
                f"{API}/system/aimodel/default/{selected['id']}", headers=headers
            ),
            "default selection",
        )

    api_key = ""
    password = ""
    print(json.dumps({
        "status": "PASS",
        "configuration_method": "official_runtime_api",
        "previous_default": {
            "id": str(previous["id"]),
            "model": previous.get("base_model"),
        },
        "selected_default": {
            "id": str(selected["id"]),
            "model": selected.get("base_model"),
        },
        "before": before,
        "after": _sanitized_config(TUNED_CONFIG),
        "credential_reexposed": False,
        "secret_values_exposed": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
