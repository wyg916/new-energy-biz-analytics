"""Apply the reviewed DeepSeek non-thinking latency profile via SQLBot API."""

from __future__ import annotations

import json
import os

import httpx


API = os.getenv("SQLBOT_RUNTIME_API_BASE_URL", "http://127.0.0.1:8000/api/v1").rstrip("/")
EXPECTED_MODEL = "deepseek-v4-flash"
CONFIG = [
    {"key": "temperature", "val": 0, "name": "temperature"},
    {
        "key": "extra_body",
        "val": {"thinking": {"type": "disabled"}},
        "name": "extra_body",
    },
    {"key": "max_tokens", "val": 1024, "name": "max_tokens"},
]


def _data(response: httpx.Response, operation: str):
    if response.status_code >= 400:
        raise RuntimeError(f"{operation} failed status={response.status_code}")
    payload = response.json()
    return payload.get("data", payload) if isinstance(payload, dict) else payload


def main() -> None:
    password = os.getenv("DEFAULT_PWD")
    if not password:
        raise RuntimeError("SQLBot runtime admin credential is unavailable")
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        login = _data(client.post(
            f"{API}/mcp/mcp_start",
            json={"username": "admin", "password": password},
        ), "login")
        token = login.get("access_token") if isinstance(login, dict) else None
        if not token:
            raise RuntimeError("SQLBot login returned no access token")
        headers = {"X-SQLBOT-TOKEN": f"Bearer {token}"}
        models = _data(client.get(f"{API}/system/aimodel", headers=headers), "model list")
        matches = [
            item for item in models
            if item.get("default_model") is True and item.get("base_model") == EXPECTED_MODEL
        ]
        if len(matches) != 1:
            raise RuntimeError("expected exactly one default DeepSeek V4 Flash model")
        model_id = str(matches[0]["id"])
        detail = _data(
            client.get(f"{API}/system/aimodel/{model_id}", headers=headers),
            "model detail",
        )
        editor = {
            key: detail[key]
            for key in (
                "name", "model_type", "base_model", "supplier", "protocol",
                "api_domain", "api_key",
            )
        }
        editor.update({"id": model_id, "default_model": False, "config_list": CONFIG})
        _data(
            client.put(f"{API}/system/aimodel", headers=headers, json=editor),
            "model update",
        )
        _data(
            client.put(f"{API}/system/aimodel/default/{model_id}", headers=headers),
            "default selection",
        )
        persisted = _data(
            client.get(f"{API}/system/aimodel/{model_id}", headers=headers),
            "model verification",
        )
    if persisted.get("config_list") != CONFIG:
        raise RuntimeError("persisted latency profile does not match the reviewed contract")
    print(json.dumps({
        "status": "PASS",
        "upstream": "SQLBot v1.10.0",
        "model": EXPECTED_MODEL,
        "thinking_mode": "disabled",
        "max_tokens": 1024,
        "configuration_method": "official_runtime_api",
        "secret_values_exposed": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
