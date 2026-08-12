"""Provision and verify the SQLBot v1.10 model through the official API.

Run this helper inside the pinned SQLBot v1.10.0 container. The provider
credential is supplied as a single JSON object on stdin so it is never placed
in a command line, tracked file, log message, or evidence artifact. SQLBot's
administrator credential is read from the container runtime environment.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass
from typing import Any

import httpx


API_BASE_URL = os.getenv(
    "SQLBOT_RUNTIME_API_BASE_URL",
    "http://127.0.0.1:8000/api/v1",
).rstrip("/")

PROVIDER_CONTRACTS = {
    "deepseek": {
        "api_domain": "https://api.deepseek.com",
        "model_name": "deepseek-v4-flash",
        "supplier": 3,
    },
    "kimi": {
        "api_domain": "https://api.moonshot.cn/v1",
        "model_name": "kimi-k2.6",
        "supplier": 8,
    },
    "mimo": {
        "api_domain": "https://api.xiaomimimo.com/v1",
        "model_name": "mimo-v2.5",
        "supplier": 0,
    },
}


@dataclass(frozen=True)
class ProviderInput:
    provider: str
    api_key: str
    api_domain: str
    model_name: str
    expected_fingerprint: str


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _read_provider_input() -> ProviderInput:
    runtime_provider = os.getenv("SQLBOT_PROVIDER")
    runtime_path = os.getenv("SQLBOT_PROVIDER_CREDENTIAL_FILE")
    if runtime_provider or runtime_path:
        if not runtime_provider or not runtime_path:
            raise RuntimeError("runtime provider reference is incomplete")
        contract = PROVIDER_CONTRACTS.get(runtime_provider)
        if contract is None:
            raise RuntimeError("provider is not an accepted SQLBot candidate")
        expected_path = f"/run/provider-credentials/{runtime_provider}"
        if runtime_path != expected_path:
            raise RuntimeError("runtime credential file is outside the allowlist")
        with open(runtime_path, encoding="utf-8") as credential_file:
            api_key = credential_file.read().strip()
        if not api_key or "\n" in api_key or "\r" in api_key:
            raise RuntimeError("runtime provider credential is invalid")
        return ProviderInput(
            provider=runtime_provider,
            api_key=api_key,
            api_domain=str(contract["api_domain"]),
            model_name=str(contract["model_name"]),
            expected_fingerprint=_fingerprint(api_key),
        )
    try:
        # Windows PowerShell 5 can prefix native-pipeline UTF-8 with a BOM.
        # Accept that transport marker while retaining the exact JSON contract.
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError("provider stdin payload is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("provider stdin payload must be an object")
    required = {
        "provider",
        "api_key",
        "api_domain",
        "model_name",
        "expected_fingerprint",
    }
    if set(payload) != required:
        raise RuntimeError("provider stdin payload fields do not match contract")
    values = {key: payload.get(key) for key in required}
    if not all(isinstance(value, str) and value for value in values.values()):
        raise RuntimeError("provider stdin payload contains an empty field")
    api_key = values["api_key"]
    expected = values["expected_fingerprint"]
    if "\n" in api_key or "\r" in api_key:
        raise RuntimeError("provider credential contains an internal newline")
    if _fingerprint(api_key) != expected:
        raise RuntimeError("provider credential fingerprint mismatch")
    contract = PROVIDER_CONTRACTS.get(values["provider"])
    if contract is None:
        raise RuntimeError("provider is not an accepted SQLBot candidate")
    if values["api_domain"].rstrip("/") != contract["api_domain"]:
        raise RuntimeError("provider API domain does not match the accepted endpoint")
    if values["model_name"] != contract["model_name"]:
        raise RuntimeError("model does not match provider discovery")
    return ProviderInput(
        provider=values["provider"],
        api_key=api_key,
        api_domain=values["api_domain"].rstrip("/"),
        model_name=values["model_name"],
        expected_fingerprint=expected,
    )


def _required_env(name: str) -> str:
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


def _admin_headers(client: httpx.Client) -> dict[str, str]:
    response = client.post(
        f"{API_BASE_URL}/mcp/mcp_start",
        json={
            "username": os.getenv("SQLBOT_ADMIN_USERNAME", "admin"),
            "password": _required_env("DEFAULT_PWD"),
        },
    )
    data = _response_data(response, "SQLBot login")
    if not isinstance(data, dict):
        raise RuntimeError("SQLBot login returned an invalid payload")
    token = data.get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("SQLBot login returned no access token")
    return {"X-SQLBOT-TOKEN": f"Bearer {token}"}


def _candidate(provider: ProviderInput) -> dict[str, Any]:
    contract = PROVIDER_CONTRACTS[provider.provider]
    provider_configs = {
        "deepseek": [
            {"key": "temperature", "val": 0, "name": "temperature"},
            # SQL generation is a constrained structured-output task. DeepSeek
            # V4 enables thinking by default, which dominated the measured
            # 4.1B latency. Use the provider's documented non-thinking mode.
            {
                "key": "extra_body",
                "val": {"thinking": {"type": "disabled"}},
                "name": "extra_body",
            },
            {"key": "max_tokens", "val": 768, "name": "max_tokens"},
            # The platform owns the only permitted one-repair loop.  Disable
            # hidden SDK retries so provider delay cannot multiply silently.
            {"key": "max_retries", "val": 0, "name": "max_retries"},
            {"key": "timeout", "val": 12, "name": "timeout"},
        ],
        "kimi": [
            {"key": "temperature", "val": 0.6, "name": "temperature"},
            {
                "key": "extra_body",
                "val": {"thinking": {"type": "disabled"}},
                "name": "extra_body",
            },
            {"key": "max_tokens", "val": 768, "name": "max_tokens"},
            {"key": "max_retries", "val": 0, "name": "max_retries"},
            {"key": "timeout", "val": 12, "name": "timeout"},
        ],
        "mimo": [
            {"key": "temperature", "val": 1.0, "name": "temperature"},
            {"key": "top_p", "val": 0.95, "name": "top_p"},
            {
                "key": "extra_body",
                "val": {"thinking": {"type": "disabled"}},
                "name": "extra_body",
            },
            {
                "key": "max_completion_tokens",
                "val": 768,
                "name": "max_completion_tokens",
            },
            {"key": "max_retries", "val": 0, "name": "max_retries"},
            {"key": "timeout", "val": 12, "name": "timeout"},
        ],
    }
    config_list = provider_configs[provider.provider]
    return {
        "name": f"p2a-runtime-{provider.provider}-{provider.model_name}",
        "model_type": 0,
        "base_model": provider.model_name,
        "supplier": contract["supplier"],
        "protocol": 1,
        # SQLBot does not reconcile existing defaults when a create
        # payload already marks the new row as default. Create/update it as a
        # non-default first, then use the dedicated default-selection API.
        "default_model": False,
        "api_domain": provider.api_domain,
        "api_key": provider.api_key,
        "config_list": config_list,
    }


def _check_model(
    client: httpx.Client,
    headers: dict[str, str],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    content_chunks = 0
    error_chunks = 0
    with client.stream(
        "POST",
        f"{API_BASE_URL}/system/aimodel/status",
        headers=headers,
        json=candidate,
        timeout=120,
    ) as response:
        status_code = response.status_code
        if status_code >= 400:
            raise RuntimeError(
                "SQLBot model check failed with "
                f"sanitized status={status_code}"
            )
        for line in response.iter_lines():
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and item.get("content"):
                content_chunks += 1
            if isinstance(item, dict) and item.get("error"):
                error_chunks += 1
    if error_chunks:
        raise RuntimeError("SQLBot model check returned a sanitized upstream error")
    return {
        "http_status": status_code,
        "content_chunk_count": content_chunks,
        "error_chunk_count": error_chunks,
        "upstream_call_completed": True,
    }


def _upsert_model(
    client: httpx.Client,
    headers: dict[str, str],
    candidate: dict[str, Any],
) -> tuple[str, str]:
    models = _response_data(
        client.get(f"{API_BASE_URL}/system/aimodel", headers=headers),
        "SQLBot model list",
    )
    if not isinstance(models, list):
        raise RuntimeError("SQLBot model list returned an invalid payload")
    existing = next(
        (
            item
            for item in models
            if isinstance(item, dict) and item.get("name") == candidate["name"]
        ),
        None,
    )
    if existing is None:
        saved = _response_data(
            client.post(
                f"{API_BASE_URL}/system/aimodel",
                headers=headers,
                json=candidate,
            ),
            "SQLBot model create",
        )
        model_id = saved.get("id") if isinstance(saved, dict) else None
        operation = "created"
    else:
        model_id = existing.get("id")
        if model_id is None:
            raise RuntimeError("SQLBot existing model id is unavailable")
        editor = dict(candidate)
        editor["id"] = str(model_id)
        _response_data(
            client.put(
                f"{API_BASE_URL}/system/aimodel",
                headers=headers,
                json=editor,
            ),
            "SQLBot model update",
        )
        operation = "updated"
    if model_id is None:
        raise RuntimeError("SQLBot model id is unavailable")
    _response_data(
        client.put(
            f"{API_BASE_URL}/system/aimodel/default/{model_id}",
            headers=headers,
        ),
        "SQLBot default model selection",
    )
    return str(model_id), operation


def _find_model_id(
    client: httpx.Client,
    headers: dict[str, str],
    model_name: str,
) -> str:
    models = _response_data(
        client.get(f"{API_BASE_URL}/system/aimodel", headers=headers),
        "SQLBot model list",
    )
    if not isinstance(models, list):
        raise RuntimeError("SQLBot model list returned an invalid payload")
    matches = [
        item
        for item in models
        if isinstance(item, dict) and item.get("name") == model_name
    ]
    if len(matches) != 1 or matches[0].get("id") is None:
        raise RuntimeError("SQLBot persisted model cardinality mismatch")
    return str(matches[0]["id"])


def _verify_persisted_model(
    client: httpx.Client,
    headers: dict[str, str],
    model_id: str,
    provider: ProviderInput,
) -> dict[str, Any]:
    persisted = _response_data(
        client.get(
            f"{API_BASE_URL}/system/aimodel/{model_id}",
            headers=headers,
        ),
        "SQLBot model detail",
    )
    if not isinstance(persisted, dict):
        raise RuntimeError("SQLBot model detail returned an invalid payload")
    persisted_key = persisted.get("api_key")
    fingerprint_match = (
        isinstance(persisted_key, str)
        and _fingerprint(persisted_key) == provider.expected_fingerprint
    )
    if not fingerprint_match:
        raise RuntimeError("SQLBot persisted credential fingerprint mismatch")
    expected = {
        "name": f"p2a-runtime-{provider.provider}-{provider.model_name}",
        "model_type": 0,
        "base_model": provider.model_name,
        "supplier": PROVIDER_CONTRACTS[provider.provider]["supplier"],
        "protocol": 1,
        "default_model": True,
        "api_domain": provider.api_domain,
    }
    contract_match = all(persisted.get(key) == value for key, value in expected.items())
    if not contract_match:
        raise RuntimeError("SQLBot persisted model contract mismatch")
    models = _response_data(
        client.get(f"{API_BASE_URL}/system/aimodel", headers=headers),
        "SQLBot model list verification",
    )
    default_count = sum(
        1
        for item in models
        if isinstance(item, dict) and item.get("default_model") is True
    )
    if default_count != 1:
        raise RuntimeError("SQLBot default model cardinality mismatch")
    return {
        "model_count": len(models),
        "default_model_count": default_count,
        "contract_match": contract_match,
        "credential_fingerprint": provider.expected_fingerprint,
        "credential_fingerprint_match": fingerprint_match,
    }


def main() -> None:
    provider = _read_provider_input()
    candidate = _candidate(provider)
    action = os.getenv("SQLBOT_MODEL_PROVISION_ACTION", "upsert")
    if action not in {"upsert", "verify"}:
        raise RuntimeError("unsupported SQLBot model provision action")
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        headers = _admin_headers(client)
        preflight = _check_model(client, headers, candidate)
        if action == "upsert":
            model_id, operation = _upsert_model(client, headers, candidate)
        else:
            model_id = _find_model_id(client, headers, candidate["name"])
            operation = "verified_after_restart"
        persisted = _verify_persisted_model(
            client,
            headers,
            model_id,
            provider,
        )
    print(json.dumps({
        "upstream": "SQLBot v1.10.0",
        "configuration_method": "official_runtime_api",
        "provider": provider.provider,
        "actual_model": provider.model_name,
        "api_domain": provider.api_domain,
        "model_configuration_id": model_id,
        "operation": operation,
        "preflight": preflight,
        **persisted,
        "secret_values_exposed": False,
        "model_response_exposed": False,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
