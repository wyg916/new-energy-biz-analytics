from __future__ import annotations

import json
import os
import re
import socket
import ssl
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class ProviderSpec:
    alias: str
    base_url: str
    preferred_model: str
    api_key: str = field(repr=False)


@dataclass(frozen=True)
class HttpResult:
    status_code: int | None
    body: bytes
    latency_ms: int
    error_type: str | None = None


Requester = Callable[
    [str, str, dict[str, str], dict[str, Any] | None, float],
    HttpResult,
]


PROVIDER_ENV = (
    ("kimi", "KIMI_BASE_URL", "KIMI_PREFERRED_MODEL", "KIMI_API_KEY"),
    ("mimo", "MIMO_BASE_URL", "MIMO_PREFERRED_MODEL", "MIMO_API_KEY"),
    (
        "deepseek",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_PREFERRED_MODEL",
        "DEEPSEEK_API_KEY",
    ),
)

SMOKE_PROMPTS = (
    (
        "chinese",
        (
            {
                "role": "user",
                "content": "请只用一句简短中文回答：1加1等于多少？",
            },
        ),
        None,
    ),
    (
        "json",
        (
            {
                "role": "system",
                "content": "你必须只输出一个严格 JSON 对象，不要 Markdown。",
            },
            {"role": "user", "content": "返回字段 status，其值为 ok。"},
        ),
        {"type": "json_object"},
    ),
    (
        "sql",
        (
            {
                "role": "system",
                "content": (
                    "你是受控 NL2SQL 验证器。只输出一个 JSON 对象，字段 sql。"
                    "SQL 必须是单条只读 SELECT，不得解释，不得执行。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "仅给定两表：orders(order_id, order_date, net_revenue, "
                    "region_id)，regions(region_id, region_name)。生成按 "
                    "region_name 汇总 net_revenue 并降序的 PostgreSQL SELECT。"
                ),
            },
        ),
        {"type": "json_object"},
    ),
)


def load_provider_specs() -> list[ProviderSpec]:
    specs: list[ProviderSpec] = []
    missing: list[str] = []
    for alias, base_env, model_env, key_env in PROVIDER_ENV:
        values = {
            base_env: os.getenv(base_env, "").strip(),
            model_env: os.getenv(model_env, "").strip(),
            key_env: os.getenv(key_env, "").strip(),
        }
        missing.extend(name for name, value in values.items() if not value)
        if all(values.values()):
            specs.append(
                ProviderSpec(
                    alias=alias,
                    base_url=values[base_env].rstrip("/"),
                    preferred_model=values[model_env],
                    api_key=values[key_env],
                )
            )
    if missing:
        raise RuntimeError(
            "provider runtime references are unavailable: "
            + ", ".join(sorted(missing))
        )
    return specs


def request_json(
    method: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None,
    timeout_seconds: float,
) -> HttpResult:
    data = (
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if payload is not None
        else None
    )
    request = Request(url, data=data, headers=headers, method=method)
    started = time.perf_counter()
    try:
        with urlopen(
            request,
            timeout=timeout_seconds,
            context=ssl.create_default_context(),
        ) as response:
            return HttpResult(
                status_code=response.status,
                body=response.read(),
                latency_ms=round((time.perf_counter() - started) * 1000),
            )
    except HTTPError as exc:
        return HttpResult(
            status_code=exc.code,
            body=exc.read(),
            latency_ms=round((time.perf_counter() - started) * 1000),
            error_type="HTTPError",
        )
    except Exception as exc:
        return HttpResult(
            status_code=None,
            body=b"",
            latency_ms=round((time.perf_counter() - started) * 1000),
            error_type=type(exc).__name__,
        )


def _safe_error(result: HttpResult) -> dict[str, Any]:
    error_code: str | None = None
    try:
        body = json.loads(result.body)
        error = body.get("error", body) if isinstance(body, dict) else {}
        if isinstance(error, dict):
            value = error.get("code") or error.get("type")
            error_code = str(value)[:80] if value is not None else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass
    return {
        "http_status": result.status_code,
        "error_code": error_code,
        "error_type": result.error_type,
    }


def select_model(
    discovered_models: list[str],
    preferred_model: str,
    provider: str,
) -> str | None:
    if preferred_model in discovered_models:
        return preferred_model
    needle = {
        "kimi": "kimi",
        "mimo": "mimo-v2.5",
        "deepseek": "deepseek",
    }[provider]
    matches = [
        model for model in discovered_models if needle in model.lower()
    ]
    return matches[0] if matches else (
        discovered_models[0] if discovered_models else None
    )


def _parse_completion(result: HttpResult) -> tuple[str, dict[str, Any]]:
    body = json.loads(result.body)
    content = body["choices"][0]["message"]["content"]
    usage = body.get("usage") or {}
    if not isinstance(content, str) or not isinstance(usage, dict):
        raise TypeError("provider completion contract is invalid")
    return content, usage


def _valid_readonly_select(sql: str) -> bool:
    upper = sql.strip().upper()
    forbidden = ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE")
    return (
        upper.startswith("SELECT")
        and not any(
            re.search(rf"\b{keyword}\b", upper)
            for keyword in forbidden
        )
        and upper.count(";") <= 1
    )


def _validate_smoke_content(check_name: str, content: str) -> bool:
    if check_name == "chinese":
        return any("\u4e00" <= character <= "\u9fff" for character in content)
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        return False
    if check_name == "json":
        return parsed.get("status") == "ok"
    return _valid_readonly_select(str(parsed.get("sql", "")))


def _auth_headers(api_key: str, method: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if method == "api-key":
        headers["api-key"] = api_key
    else:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _check_passed(check: dict[str, Any]) -> bool:
    return bool(
        check.get(
            "success",
            check.get("rejected", check.get("timeout_observed", False)),
        )
    )


def validate_provider(
    spec: ProviderSpec,
    *,
    requester: Requester = request_json,
    timeout_seconds: float = 30.0,
    timeout_probe_seconds: float = 0.001,
) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}
    result: dict[str, Any] = {
        "provider": spec.alias,
        "base_url": spec.base_url,
        "dns": False,
        "discovered_models": [],
        "selected_model": None,
        "auth_method": "Authorization: Bearer",
        "checks": checks,
        "final_status": "FAIL",
    }
    try:
        socket.getaddrinfo(urlsplit(spec.base_url).hostname, 443)
        result["dns"] = True
    except Exception as exc:
        checks["dns"] = {
            "success": False,
            "error_type": type(exc).__name__,
        }
        return result

    auth_methods = ["bearer"]
    if spec.alias == "mimo":
        auth_methods.append("api-key")
    models_result: HttpResult | None = None
    selected_auth = "bearer"
    for auth_method in auth_methods:
        candidate = requester(
            "GET",
            f"{spec.base_url}/models",
            _auth_headers(spec.api_key, auth_method),
            None,
            timeout_seconds,
        )
        models_result = candidate
        selected_auth = auth_method
        if candidate.status_code == 200:
            break
        if candidate.status_code not in {401, 403}:
            break
    assert models_result is not None
    result["auth_method"] = (
        "api-key" if selected_auth == "api-key" else "Authorization: Bearer"
    )
    if models_result.status_code != 200:
        checks["models"] = {
            "success": False,
            "latency_ms": models_result.latency_ms,
            **_safe_error(models_result),
        }
        return result

    try:
        body = json.loads(models_result.body)
        models = body.get("data", []) if isinstance(body, dict) else []
        discovered = [
            str(item["id"])
            for item in models
            if isinstance(item, dict) and item.get("id")
        ]
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, KeyError) as exc:
        checks["models"] = {
            "success": False,
            "latency_ms": models_result.latency_ms,
            "error_type": type(exc).__name__,
        }
        return result
    selected_model = select_model(
        discovered,
        spec.preferred_model,
        spec.alias,
    )
    result["discovered_models"] = discovered
    result["selected_model"] = selected_model
    checks["models"] = {
        "success": selected_model is not None,
        "http_status": 200,
        "latency_ms": models_result.latency_ms,
        "count": len(discovered),
        "preferred_present": spec.preferred_model in discovered,
    }
    if selected_model is None:
        return result

    headers = _auth_headers(spec.api_key, selected_auth)
    for check_name, messages, response_format in SMOKE_PROMPTS:
        payload: dict[str, Any] = {
            "model": selected_model,
            "messages": list(messages),
            "stream": False,
            "max_tokens": 256,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        completion = requester(
            "POST",
            f"{spec.base_url}/chat/completions",
            headers,
            payload,
            timeout_seconds,
        )
        if completion.status_code != 200:
            checks[check_name] = {
                "success": False,
                "latency_ms": completion.latency_ms,
                **_safe_error(completion),
            }
            continue
        try:
            content, usage = _parse_completion(completion)
            valid = _validate_smoke_content(check_name, content)
            checks[check_name] = {
                "success": valid,
                "http_status": 200,
                "latency_ms": completion.latency_ms,
                "usage_available": bool(usage),
                "total_tokens": usage.get("total_tokens"),
            }
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            TypeError,
            KeyError,
            IndexError,
        ) as exc:
            checks[check_name] = {
                "success": False,
                "http_status": 200,
                "latency_ms": completion.latency_ms,
                "error_type": type(exc).__name__,
            }

    invalid_model = requester(
        "POST",
        f"{spec.base_url}/chat/completions",
        headers,
        {
            "model": "codex-invalid-model-runtime-check",
            "messages": [{"role": "user", "content": "ping"}],
            "stream": False,
            "max_tokens": 8,
        },
        timeout_seconds,
    )
    checks["invalid_model"] = {
        "rejected": bool(
            invalid_model.status_code and invalid_model.status_code >= 400
        ),
        "latency_ms": invalid_model.latency_ms,
        **_safe_error(invalid_model),
    }
    timeout_probe = requester(
        "POST",
        f"{spec.base_url}/chat/completions",
        headers,
        {
            "model": selected_model,
            "messages": [{"role": "user", "content": "timeout check"}],
            "stream": False,
            "max_tokens": 8,
        },
        timeout_probe_seconds,
    )
    checks["timeout"] = {
        "timeout_observed": timeout_probe.error_type
        in {"TimeoutError", "URLError", "socket.timeout"},
        "error_type": timeout_probe.error_type,
        "latency_ms": timeout_probe.latency_ms,
        "sanitized": True,
    }
    required = ("models", "chinese", "json", "sql", "invalid_model", "timeout")
    result["final_status"] = (
        "PASS" if all(_check_passed(checks[name]) for name in required) else "FAIL"
    )
    return result


def validate_all_providers(
    specs: list[ProviderSpec],
    *,
    requester: Requester = request_json,
    timeout_seconds: float = 30.0,
    timeout_probe_seconds: float = 0.001,
) -> dict[str, Any]:
    providers = [
        validate_provider(
            spec,
            requester=requester,
            timeout_seconds=timeout_seconds,
            timeout_probe_seconds=timeout_probe_seconds,
        )
        for spec in specs
    ]
    usable = sum(item["final_status"] == "PASS" for item in providers)
    return {
        "runtime_status": "PASS" if usable else "PROVIDER_AUTHENTICATION_FAILED",
        "usable_provider_count": usable,
        "providers": providers,
        "secret_values_exposed": False,
    }
