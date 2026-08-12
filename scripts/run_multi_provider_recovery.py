"""Run sanitized discovery and health probes for the three approved providers."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.evaluation.official_model_provider_validation import (  # noqa: E402
    OFFICIAL_PROVIDER_CONFIG,
    ProviderSpec,
    _completion,
    _fingerprint,
    _models_with_single_retry,
    _request_id,
    _response_payload,
    _safe_error,
    request_json,
)


PROVIDERS = (
    ("kimi", "kimi-k2.6", "bearer"),
    ("mimo", "mimo-v2.5", "api-key"),
    ("deepseek", "deepseek-v4-flash", "bearer"),
)


def _credential(root: Path, provider: str) -> tuple[str, str]:
    path = root / provider
    value = path.read_text(encoding="utf-8").strip()
    if not value.startswith("sk-") or "\n" in value or "\r" in value:
        raise RuntimeError(f"{provider} runtime credential is invalid")
    return value, _fingerprint(value)


def _specs(credential_root: Path) -> list[tuple[ProviderSpec, str]]:
    result = []
    for provider, model, auth in PROVIDERS:
        secret, fingerprint = _credential(credential_root, provider)
        config = OFFICIAL_PROVIDER_CONFIG[provider]
        if config["preferred_model"] != model:
            raise RuntimeError(f"{provider} frozen model contract drifted")
        result.append((ProviderSpec(
            alias=provider,
            base_url=str(config["base_url"]),
            preferred_model=model,
            api_key=secret,
            key_fingerprint=fingerprint,
        ), auth))
    return result


def _percentile(values: list[int], quantile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * quantile + 0.999999)))
    return ordered[index]


def _discovery(spec: ProviderSpec, auth: str, timeout: float) -> dict[str, Any]:
    models_result, attempts = _models_with_single_retry(
        spec,
        request_json,
        timeout,
        auth_method=auth,
    )
    models: list[str] = []
    models_parse_valid = False
    if models_result.status_code == 200:
        try:
            payload = _response_payload(models_result)
            models = [
                str(item["id"])
                for item in payload.get("data", [])
                if isinstance(item, dict) and item.get("id")
            ]
            models_parse_valid = True
        except (ValueError, KeyError, TypeError):
            models_parse_valid = False
    target_present = spec.preferred_model in models
    minimal: dict[str, Any] = {
        "http_status": None,
        "success": False,
        "latency_ms": None,
        "response_valid": False,
    }
    if target_present:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if auth == "api-key":
            headers["api-key"] = spec.api_key
        else:
            headers["Authorization"] = f"Bearer {spec.api_key}"
        messages = [{"role": "user", "content": "只回复 OK"}]
        request_payload: dict[str, Any] = {
            "model": spec.preferred_model,
            "messages": messages,
            "stream": False,
        }
        if spec.alias == "mimo":
            request_payload.update({
                "messages": [
                    {
                        "role": "system",
                        "content": "你是MiMo（中文名称也是MiMo），是小米公司研发的AI智能助手。",
                    },
                    *messages,
                ],
                "max_completion_tokens": 32,
                "temperature": 1.0,
                "top_p": 0.95,
                "thinking": {"type": "disabled"},
            })
        elif spec.alias == "kimi":
            request_payload.update({
                "max_tokens": 32,
                "temperature": 0.6,
                "thinking": {"type": "disabled"},
            })
        else:
            request_payload.update({"max_tokens": 32, "temperature": 0})
            if spec.alias == "deepseek":
                request_payload["thinking"] = {"type": "disabled"}
        response = request_json(
            "POST",
            f"{spec.base_url}/chat/completions",
            headers,
            request_payload,
            timeout,
        )
        chat_parse_valid = False
        response_model = None
        if response.status_code == 200:
            try:
                content, _usage, response_model = _completion(response)
                chat_parse_valid = bool(content.strip())
            except (ValueError, KeyError, IndexError, TypeError):
                chat_parse_valid = False
        minimal = {
            "http_status": response.status_code,
            "success": response.status_code == 200 and chat_parse_valid,
            "latency_ms": response.latency_ms,
            "request_id": _request_id(response),
            "response_model": response_model,
            "response_valid": chat_parse_valid,
        }
    passed = (
        models_result.status_code == 200
        and models_parse_valid
        and target_present
        and minimal["success"] is True
    )
    return {
        "provider": spec.alias,
        "model": spec.preferred_model,
        "credential_ref": f"runtime-file://provider-credentials/{spec.alias}",
        "credential_fingerprint_sha256_12": spec.key_fingerprint,
        "auth_method": "api-key" if auth == "api-key" else "Authorization: Bearer",
        "model_discovery": {
            **_safe_error(models_result),
            "attempts": attempts,
            "latency_ms": models_result.latency_ms,
            "response_valid": models_parse_valid,
            "model_count": len(models),
            "target_present": target_present,
            "discovered_models": models,
        },
        "minimal_chat": minimal,
        "status": "PASS" if passed else "FAIL",
    }


def _health(spec: ProviderSpec, auth: str, count: int, timeout: float) -> dict[str, Any]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if auth == "api-key":
        headers["api-key"] = spec.api_key
    else:
        headers["Authorization"] = f"Bearer {spec.api_key}"
    payload: dict[str, Any] = {
        "model": spec.preferred_model,
        "messages": [{"role": "user", "content": "只回复 OK"}],
        "stream": False,
    }
    if spec.alias == "mimo":
        payload.update({
            "messages": [
                {
                    "role": "system",
                    "content": "你是MiMo（中文名称也是MiMo），是小米公司研发的AI智能助手。",
                },
                {"role": "user", "content": "只回复 OK"},
            ],
            "max_completion_tokens": 32,
            "temperature": 1.0,
            "top_p": 0.95,
            "thinking": {"type": "disabled"},
        })
    elif spec.alias == "kimi":
        payload.update({
            "max_tokens": 32,
            "temperature": 0.6,
            "thinking": {"type": "disabled"},
        })
    elif spec.alias == "deepseek":
        payload.update({
            "max_tokens": 32,
            "temperature": 0,
            "thinking": {"type": "disabled"},
        })
    else:
        payload.update({"max_tokens": 32, "temperature": 0})
    samples = []
    for index in range(1, count + 1):
        response = request_json(
            "POST",
            f"{spec.base_url}/chat/completions",
            headers,
            payload,
            timeout,
        )
        valid = False
        response_model = None
        if response.status_code == 200:
            try:
                content, _usage, response_model = _completion(response)
                valid = bool(content.strip())
            except (ValueError, KeyError, IndexError, TypeError):
                valid = False
        samples.append({
            "sequence": index,
            "http_status": response.status_code,
            "success": response.status_code == 200 and valid,
            "timeout": response.error_type in {"TimeoutError", "URLError", "socket.timeout"},
            "latency_ms": response.latency_ms,
            "response_valid": valid,
            "response_model": response_model,
            "request_id": _request_id(response),
            **({} if response.status_code == 200 else _safe_error(response)),
        })
    latencies = [int(item["latency_ms"]) for item in samples]
    passed = all(item["success"] for item in samples)
    return {
        "provider": spec.alias,
        "model": spec.preferred_model,
        "credential_ref": f"runtime-file://provider-credentials/{spec.alias}",
        "probe_count": count,
        "success_count": sum(bool(item["success"]) for item in samples),
        "timeout_count": sum(bool(item["timeout"]) for item in samples),
        "response_valid_count": sum(bool(item["response_valid"]) for item in samples),
        "latency_ms": {
            "p50": round(statistics.median(latencies)) if latencies else None,
            "p95": _percentile(latencies, 0.95),
            "min": min(latencies) if latencies else None,
            "max": max(latencies) if latencies else None,
        },
        "samples": samples,
        "status": "PASS" if passed else "FAIL",
    }


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credential-dir", type=Path, required=True)
    parser.add_argument("--discovery-output", type=Path, required=True)
    parser.add_argument("--health-output", type=Path, required=True)
    parser.add_argument("--health-count", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args()
    if args.health_count < 5:
        raise RuntimeError("health probe count must be at least 5")
    specs = _specs(args.credential_dir)
    discovery_rows = [
        _discovery(spec, auth, args.timeout_seconds)
        for spec, auth in specs
    ]
    discovery = {
        "evidence_type": "integration41full_provider_discovery",
        "status": "PASS" if all(row["status"] == "PASS" for row in discovery_rows) else "FAIL",
        "providers": discovery_rows,
        "secret_values_exposed": False,
    }
    _write(args.discovery_output, discovery)
    health_rows = [
        _health(spec, auth, args.health_count, args.timeout_seconds)
        for spec, auth in specs
    ]
    health = {
        "evidence_type": "integration41full_provider_health_matrix",
        "status": "PASS" if all(row["status"] == "PASS" for row in health_rows) else "FAIL",
        "providers": health_rows,
        "secret_values_exposed": False,
    }
    _write(args.health_output, health)
    for spec, _auth in specs:
        object.__setattr__(spec, "api_key", "")
    print(json.dumps({
        "discovery": {"status": discovery["status"], "providers": [
            {"provider": row["provider"], "model": row["model"], "status": row["status"]}
            for row in discovery_rows
        ]},
        "health": {"status": health["status"], "providers": [
            {
                "provider": row["provider"],
                "model": row["model"],
                "status": row["status"],
                "success_count": row["success_count"],
                "p50": row["latency_ms"]["p50"],
                "p95": row["latency_ms"]["p95"],
            }
            for row in health_rows
        ]},
        "secret_values_exposed": False,
    }, ensure_ascii=False))
    raise SystemExit(0 if discovery["status"] == health["status"] == "PASS" else 2)


if __name__ == "__main__":
    main()
