from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import ssl
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


OFFICIAL_PROVIDER_CONFIG = {
    "kimi": {
        "base_url": "https://api.moonshot.cn/v1",
        "preferred_model": "kimi-k2.6",
        "key_env": "KIMI_API_KEY",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "preferred_model": "deepseek-v4-flash",
        "key_env": "DEEPSEEK_API_KEY",
    },
    "mimo": {
        "base_url": "https://api.xiaomimimo.com/v1",
        "preferred_model": "mimo-v2.5",
        "key_env": "MIMO_API_KEY",
    },
}

ENV_FIELD_NAMES = (
    "KIMI_API_KEY",
    "KIMI_BASE_URL",
    "KIMI_MODEL",
    "MIMO_API_KEY",
    "MIMO_BASE_URL",
    "MIMO_MODEL",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
)

KEY_FIELD_NAMES = frozenset({
    "KIMI_API_KEY",
    "MIMO_API_KEY",
    "DEEPSEEK_API_KEY",
})


@dataclass(frozen=True)
class ProviderSpec:
    alias: str
    base_url: str
    preferred_model: str
    api_key: str = field(repr=False)
    key_fingerprint: str


@dataclass(frozen=True)
class HttpResult:
    status_code: int | None
    body: bytes
    latency_ms: int
    headers: dict[str, str] = field(default_factory=dict)
    error_type: str | None = None


Requester = Callable[
    [str, str, dict[str, str], dict[str, Any] | None, float],
    HttpResult,
]


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _contains_invisible(value: str) -> bool:
    return any(
        unicodedata.category(character) in {"Cc", "Cf"}
        for character in value
    )


def _clean_env_value(raw_value: str) -> str:
    value = raw_value.strip()
    if (
        len(value) >= 2
        and value[0] == value[-1]
        and value[0] in {"'", '"'}
    ):
        value = value[1:-1]
    if "\r" in value or "\n" in value:
        raise ValueError("environment value contains an internal newline")
    if not value:
        raise ValueError("environment value is empty")
    return value


def parse_env_file(path: Path) -> tuple[dict[str, str], dict[str, Any]]:
    raw_bytes = path.read_bytes()
    bom_present = raw_bytes.startswith(b"\xef\xbb\xbf")
    text = raw_bytes.decode("utf-8-sig")
    values: dict[str, str] = {}
    audits: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    for line_number, source_line in enumerate(text.splitlines(), start=1):
        line = source_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in source_line:
            raise ValueError(f"invalid env line at {line_number}")
        name, raw_value = source_line.split("=", 1)
        name = name.strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", name):
            raise ValueError(f"invalid env name at {line_number}")
        if name in values:
            duplicates.append(name)
            continue
        cleaned = _clean_env_value(raw_value)
        values[name] = cleaned
        if name in KEY_FIELD_NAMES:
            audits[name] = {
                "present": True,
                "raw_length": len(raw_value),
                "cleaned_length": len(cleaned),
                "prefix": cleaned[:3],
                "fingerprint_sha256_12": _fingerprint(cleaned),
                "contains_invisible_characters": _contains_invisible(cleaned),
            }
    if duplicates:
        raise ValueError(
            "duplicate environment variables: "
            + ", ".join(sorted(set(duplicates)))
        )
    missing = sorted(set(ENV_FIELD_NAMES) - set(values))
    if missing:
        raise ValueError(
            "required environment variables are missing: "
            + ", ".join(missing)
        )
    for name in KEY_FIELD_NAMES:
        if _contains_invisible(values[name]):
            raise ValueError(f"{name} contains invisible characters")
    return values, {
        "source": "external_runtime_env",
        "encoding": "utf-8-sig",
        "bom_present": bom_present,
        "duplicates": [],
        "fields": audits,
        "secret_values_exposed": False,
    }


def load_provider_specs(
    values: Mapping[str, str] | None = None,
) -> list[ProviderSpec]:
    source = values if values is not None else os.environ
    specs: list[ProviderSpec] = []
    for alias, config in OFFICIAL_PROVIDER_CONFIG.items():
        prefix = alias.upper()
        base_url = str(source.get(f"{prefix}_BASE_URL", "")).strip().rstrip("/")
        preferred_model = str(
            source.get(f"{prefix}_MODEL")
            or source.get(f"{prefix}_PREFERRED_MODEL", "")
        ).strip()
        key = str(source.get(str(config["key_env"]), ""))
        if not base_url or not preferred_model or not key:
            raise RuntimeError(f"{alias} runtime references are unavailable")
        if base_url != config["base_url"]:
            raise RuntimeError(f"{alias} base URL is outside the approved contract")
        if alias == "mimo" and preferred_model != config["preferred_model"]:
            raise RuntimeError("MiMo model is outside the approved contract")
        specs.append(ProviderSpec(
            alias=alias,
            base_url=base_url,
            preferred_model=preferred_model,
            api_key=key,
            key_fingerprint=_fingerprint(key),
        ))
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
                headers={key.lower(): value for key, value in response.headers.items()},
            )
    except HTTPError as exc:
        return HttpResult(
            status_code=exc.code,
            body=exc.read(),
            latency_ms=round((time.perf_counter() - started) * 1000),
            headers={key.lower(): value for key, value in exc.headers.items()},
            error_type="HTTPError",
        )
    except Exception as exc:
        return HttpResult(
            status_code=None,
            body=b"",
            latency_ms=round((time.perf_counter() - started) * 1000),
            error_type=type(exc).__name__,
        )


def _request_id(result: HttpResult) -> str | None:
    for name in ("x-request-id", "request-id", "x-moonshot-request-id"):
        if result.headers.get(name):
            return result.headers[name][:128]
    return None


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
        "request_id": _request_id(result),
    }


def _response_payload(result: HttpResult) -> dict[str, Any]:
    body = json.loads(result.body)
    if not isinstance(body, dict):
        raise TypeError("provider response is not an object")
    return body


def _completion(result: HttpResult) -> tuple[str, dict[str, Any], str | None]:
    body = _response_payload(result)
    content = body["choices"][0]["message"]["content"]
    usage = body.get("usage") or {}
    response_model = body.get("model")
    if not isinstance(content, str) or not isinstance(usage, dict):
        raise TypeError("provider completion contract is invalid")
    return (
        content,
        {
            key: usage.get(key)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            if usage.get(key) is not None
        },
        str(response_model) if response_model else None,
    )


def _select_model(models: list[str], preferred_model: str, alias: str) -> str | None:
    del alias
    return preferred_model if preferred_model in models else None


def _valid_sql(content: str) -> bool:
    sql = content.strip()
    upper = sql.upper()
    forbidden = ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE")
    return (
        upper.startswith("SELECT")
        and not upper.startswith("SELECT ```")
        and not any(re.search(rf"\b{word}\b", upper) for word in forbidden)
        and upper.count(";") <= 1
        and "```" not in sql
    )


def _smoke_messages(alias: str, check_name: str) -> list[dict[str, str]]:
    identity = (
        [{
            "role": "system",
            "content": "你是MiMo，是小米公司研发的AI智能助手。",
        }]
        if alias == "mimo"
        else []
    )
    if check_name == "text":
        return identity + [{"role": "user", "content": "只回复 OK"}]
    if check_name == "json":
        return identity + [{
            "role": "user",
            "content": (
                "只返回严格 JSON，不要 Markdown："
                f'{{"status":"ok","provider":"{alias}"}}'
            ),
        }]
    return identity + [
        {
            "role": "system",
            "content": (
                "只输出一条 PostgreSQL SELECT。禁止解释、Markdown 和写操作。"
            ),
        },
        {
            "role": "user",
            "content": (
                "Schema: orders(order_id bigint, order_date date, region varchar, "
                "revenue numeric)。统计 2026-01-01 至 2026-01-31 各区域收入，"
                "按收入从高到低排序。"
            ),
        },
    ]


def _chat_payload(
    alias: str,
    model: str,
    check_name: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": _smoke_messages(alias, check_name),
        "stream": False,
    }
    if alias == "mimo":
        payload.update({
            "max_completion_tokens": 32 if check_name == "text" else 256,
            "temperature": 1.0,
            "top_p": 0.95,
            "thinking": {"type": "disabled"},
        })
    elif alias == "kimi":
        payload.update({
            "max_tokens": 32 if check_name == "text" else 256,
            "temperature": 0.6,
            "thinking": {"type": "disabled"},
        })
    elif alias == "deepseek":
        payload["thinking"] = {"type": "disabled"}
    if check_name == "json":
        payload["response_format"] = {"type": "json_object"}
    return payload


def _validate_content(alias: str, check_name: str, content: str) -> bool:
    if check_name == "text":
        return content.strip().upper() == "OK"
    if check_name == "json":
        parsed = json.loads(content)
        return parsed == {"status": "ok", "provider": alias}
    return _valid_sql(content)


def _run_smoke(
    spec: ProviderSpec,
    *,
    model: str,
    auth_method: str,
    requester: Requester,
    timeout_seconds: float,
    initial_text_result: HttpResult | None = None,
) -> tuple[dict[str, Any], str]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if auth_method == "api-key":
        headers["api-key"] = spec.api_key
    else:
        headers["Authorization"] = f"Bearer {spec.api_key}"
    checks: dict[str, Any] = {}
    selected_model = model
    for check_name in ("text", "json", "sql"):
        result = initial_text_result if check_name == "text" else None
        if result is None:
            result = requester(
                "POST",
                f"{spec.base_url}/chat/completions",
                headers,
                _chat_payload(spec.alias, selected_model, check_name),
                timeout_seconds,
            )
        check: dict[str, Any] = {
            "http_status": result.status_code,
            "latency_ms": result.latency_ms,
            "request_id": _request_id(result),
            "success": False,
        }
        if result.status_code == 200:
            try:
                content, usage, response_model = _completion(result)
                if response_model:
                    selected_model = response_model
                check.update({
                    "success": _validate_content(
                        spec.alias,
                        check_name,
                        content,
                    ),
                    "usage": usage,
                    "response_model": response_model,
                })
            except (
                UnicodeDecodeError,
                json.JSONDecodeError,
                KeyError,
                IndexError,
                TypeError,
            ) as exc:
                check["error_type"] = type(exc).__name__
        else:
            check.update(_safe_error(result))
        checks[check_name] = check
    return checks, selected_model


def _models_with_single_retry(
    spec: ProviderSpec,
    requester: Requester,
    timeout_seconds: float,
    auth_method: str = "bearer",
) -> tuple[HttpResult, int]:
    headers = {"Accept": "application/json"}
    if auth_method == "api-key":
        headers["api-key"] = spec.api_key
    else:
        headers["Authorization"] = f"Bearer {spec.api_key}"
    attempts = 0
    result: HttpResult | None = None
    while attempts < 2:
        attempts += 1
        result = requester(
            "GET",
            f"{spec.base_url}/models",
            headers,
            None,
            timeout_seconds,
        )
        if result.status_code != 401:
            break
    assert result is not None
    return result, attempts


def _base_result(spec: ProviderSpec) -> dict[str, Any]:
    return {
        "provider": spec.alias,
        "base_url": spec.base_url,
        "auth_method": None,
        "selected_model": None,
        "discovered_models": [],
        "dns": False,
        "file_key_fingerprint_sha256_12": spec.key_fingerprint,
        "request_key_fingerprint_sha256_12": _fingerprint(spec.api_key),
        "fingerprint_match": spec.key_fingerprint == _fingerprint(spec.api_key),
        "checks": {},
        "final_status": "FAIL",
    }


def _validate_models_provider(
    spec: ProviderSpec,
    *,
    requester: Requester,
    timeout_seconds: float,
) -> dict[str, Any]:
    result = _base_result(spec)
    result["auth_method"] = "Authorization: Bearer"
    try:
        socket.getaddrinfo(urlsplit(spec.base_url).hostname, 443)
        result["dns"] = True
    except Exception as exc:
        result["checks"]["dns"] = {"error_type": type(exc).__name__}
        return result
    models_result, attempts = _models_with_single_retry(
        spec,
        requester,
        timeout_seconds,
    )
    models_check = {
        **_safe_error(models_result),
        "attempts": attempts,
        "latency_ms": models_result.latency_ms,
        "success": False,
    }
    if models_result.status_code != 200:
        result["checks"]["models"] = models_check
        return result
    try:
        payload = _response_payload(models_result)
        models = [
            str(item["id"])
            for item in payload.get("data", [])
            if isinstance(item, dict) and item.get("id")
        ]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        models_check["error_type"] = type(exc).__name__
        result["checks"]["models"] = models_check
        return result
    selected_model = _select_model(models, spec.preferred_model, spec.alias)
    models_check.update({"success": selected_model is not None, "count": len(models)})
    result["checks"]["models"] = models_check
    result["discovered_models"] = models
    result["selected_model"] = selected_model
    if selected_model is None:
        return result
    smoke, selected_model = _run_smoke(
        spec,
        model=selected_model,
        auth_method="bearer",
        requester=requester,
        timeout_seconds=timeout_seconds,
    )
    result["checks"].update(smoke)
    result["selected_model"] = selected_model
    result["final_status"] = (
        "PASS"
        if all(smoke[name]["success"] for name in ("text", "json", "sql"))
        else "FAIL"
    )
    return result


def _validate_mimo(
    spec: ProviderSpec,
    *,
    requester: Requester,
    timeout_seconds: float,
) -> dict[str, Any]:
    result = _base_result(spec)
    try:
        socket.getaddrinfo(urlsplit(spec.base_url).hostname, 443)
        result["dns"] = True
    except Exception as exc:
        result["checks"]["dns"] = {"error_type": type(exc).__name__}
        return result
    models_result, attempts = _models_with_single_retry(
        spec,
        requester,
        timeout_seconds,
        auth_method="api-key",
    )
    models_check = {
        **_safe_error(models_result),
        "attempts": attempts,
        "latency_ms": models_result.latency_ms,
        "success": False,
    }
    result["auth_method"] = "api-key"
    if models_result.status_code != 200:
        result["checks"]["models"] = models_check
        return result
    try:
        payload = _response_payload(models_result)
        models = [
            str(item["id"])
            for item in payload.get("data", [])
            if isinstance(item, dict) and item.get("id")
        ]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        models_check["error_type"] = type(exc).__name__
        result["checks"]["models"] = models_check
        return result
    selected_model = _select_model(models, spec.preferred_model, spec.alias)
    models_check.update({
        "success": selected_model is not None,
        "count": len(models),
        "preferred_present": spec.preferred_model in models,
    })
    result["checks"]["models"] = models_check
    result["discovered_models"] = models
    result["selected_model"] = selected_model
    if selected_model is None:
        return result
    smoke, selected_model = _run_smoke(
        spec,
        model=selected_model,
        auth_method="api-key",
        requester=requester,
        timeout_seconds=timeout_seconds,
    )
    result["checks"].update(smoke)
    result["selected_model"] = selected_model
    result["final_status"] = (
        "PASS"
        if all(smoke[name]["success"] for name in ("text", "json", "sql"))
        else "FAIL"
    )
    return result


def validate_provider(
    spec: ProviderSpec,
    *,
    requester: Requester = request_json,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    if spec.alias == "mimo":
        return _validate_mimo(
            spec,
            requester=requester,
            timeout_seconds=timeout_seconds,
        )
    return _validate_models_provider(
        spec,
        requester=requester,
        timeout_seconds=timeout_seconds,
    )


def _all_credentials_rejected(providers: list[dict[str, Any]]) -> bool:
    by_alias = {item["provider"]: item for item in providers}
    try:
        return (
            by_alias["kimi"]["checks"]["models"]["http_status"] == 401
            and by_alias["deepseek"]["checks"]["models"]["http_status"] == 401
            and by_alias["mimo"]["checks"]["models"]["http_status"] == 401
        )
    except (KeyError, TypeError):
        return False


def validate_all_providers(
    specs: list[ProviderSpec],
    *,
    requester: Requester = request_json,
    timeout_seconds: float = 30.0,
    env_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    providers = [
        validate_provider(
            spec,
            requester=requester,
            timeout_seconds=timeout_seconds,
        )
        for spec in specs
    ]
    usable = sum(item["final_status"] == "PASS" for item in providers)
    if usable:
        runtime_status = "PASS"
    elif _all_credentials_rejected(providers):
        runtime_status = "PROVIDER_CREDENTIALS_REJECTED_BY_OFFICIAL_API"
    else:
        runtime_status = "PROVIDER_RUNTIME_NOT_AVAILABLE"
    return {
        "runtime_status": runtime_status,
        "usable_provider_count": usable,
        "env_audit": env_audit,
        "providers": providers,
        "secret_values_exposed": False,
    }
