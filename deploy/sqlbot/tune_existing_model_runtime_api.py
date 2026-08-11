"""Tune the accepted persisted SQLBot model without re-exposing its key.

The helper uses SQLBot's official model API, retains the persisted credential
in memory only, and emits a sanitized before/after configuration record.
"""

from __future__ import annotations

import json
import os

import httpx


API = os.getenv(
    "SQLBOT_RUNTIME_API_BASE_URL",
    "http://127.0.0.1:8000/api/v1",
).rstrip("/")
EXPECTED = {
    "base_model": "deepseek-v4-flash",
    "api_domain": "https://api.deepseek.com",
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


def _data(response: httpx.Response, operation: str):
    if response.status_code >= 400:
        raise RuntimeError(f"{operation} failed with status={response.status_code}")
    payload = response.json()
    return payload.get("data", payload) if isinstance(payload, dict) else payload


def _sanitized_config(value) -> list[dict]:
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
    password = os.getenv("DEFAULT_PWD")
    if not password:
        raise RuntimeError("SQLBot admin CredentialReference is unavailable")
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        login = _data(client.post(
            f"{API}/mcp/mcp_start",
            json={"username": os.getenv("SQLBOT_ADMIN_USERNAME", "admin"), "password": password},
        ), "login")
        token = login.get("access_token") if isinstance(login, dict) else None
        if not token:
            raise RuntimeError("SQLBot admin authentication returned no token")
        headers = {"X-SQLBOT-TOKEN": f"Bearer {token}"}
        models = _data(client.get(f"{API}/system/aimodel", headers=headers), "model list")
        if not isinstance(models, list):
            raise RuntimeError("SQLBot model list response is invalid")
        model_details = []
        for item in models:
            if not isinstance(item, dict) or item.get("id") is None:
                continue
            candidate_detail = _data(
                client.get(
                    f"{API}/system/aimodel/{item['id']}",
                    headers=headers,
                ),
                "model detail",
            )
            if isinstance(candidate_detail, dict):
                model_details.append(candidate_detail)
        accepted_candidates = [
            item for item in model_details
            if item.get("base_model") in {"deepseek-v4-flash", "kimi-k2.6"}
            and item.get("api_domain") in {
                "https://api.deepseek.com",
                "https://api.moonshot.cn/v1",
            }
        ]
        defaults = [item for item in models if item.get("default_model") is True]
        if len(defaults) != 1:
            raise RuntimeError("SQLBot default model cardinality mismatch")
        model_id = defaults[0].get("id")
        detail = _data(
            client.get(f"{API}/system/aimodel/{model_id}", headers=headers),
            "model detail",
        )
        if any(detail.get(key) != value for key, value in EXPECTED.items()):
            raise RuntimeError("persisted provider is outside the accepted contract")
        api_key = detail.get("api_key")
        if not isinstance(api_key, str) or not api_key:
            raise RuntimeError("persisted provider CredentialReference is unavailable")
        before = _sanitized_config(detail.get("config") or detail.get("config_list"))
        editor = {
            "id": str(model_id),
            "name": detail["name"],
            "model_type": detail["model_type"],
            "base_model": detail["base_model"],
            "supplier": detail["supplier"],
            "protocol": detail["protocol"],
            "default_model": False,
            "api_domain": detail["api_domain"],
            "api_key": api_key,
            "config_list": TUNED_CONFIG,
        }
        _data(
            client.put(f"{API}/system/aimodel", headers=headers, json=editor),
            "model update",
        )
        _data(
            client.put(f"{API}/system/aimodel/default/{model_id}", headers=headers),
            "default selection",
        )
    api_key = ""
    password = ""
    print(json.dumps({
        "status": "PASS",
        "provider": "deepseek",
        "model": EXPECTED["base_model"],
        "before": before,
        "after": _sanitized_config(TUNED_CONFIG),
        "configured_model_count": len(models),
        "accepted_candidate_count": len(accepted_candidates),
        "accepted_candidates": [
            {
                "id": str(item.get("id")),
                "model": item.get("base_model"),
                "default": item.get("default_model") is True,
            }
            for item in accepted_candidates
        ],
        "hidden_sdk_retries": 0,
        "generation_timeout_seconds": 12,
        "max_output_tokens": 768,
        "credential_reexposed": False,
        "secret_values_exposed": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
