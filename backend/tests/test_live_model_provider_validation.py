import json

import pytest

from app.evaluation.live_model_provider_validation import (
    HttpResult,
    ProviderSpec,
    load_provider_specs,
    select_model,
    validate_all_providers,
)


pytestmark = pytest.mark.no_db


def _json_result(body: dict, *, status: int = 200, latency: int = 5) -> HttpResult:
    return HttpResult(
        status_code=status,
        body=json.dumps(body).encode(),
        latency_ms=latency,
        error_type="HTTPError" if status >= 400 else None,
    )


def test_live_provider_report_is_complete_and_never_exposes_key(monkeypatch):
    monkeypatch.setattr(
        "app.evaluation.live_model_provider_validation.socket.getaddrinfo",
        lambda *_args: [(None, None, None, None, None)],
    )
    secret = "sk-live-secret-must-not-appear"
    specs = [ProviderSpec("kimi", "https://example.test/v1", "kimi-k2.6", secret)]

    def requester(method, url, headers, payload, timeout):
        assert secret in headers.get("Authorization", "")
        if method == "GET":
            return _json_result({"data": [{"id": "kimi-k2.6"}]})
        if timeout < 0.01:
            return HttpResult(None, b"", 1, "TimeoutError")
        if payload["model"] == "codex-invalid-model-runtime-check":
            return _json_result(
                {"error": {"code": "model_not_found"}},
                status=404,
            )
        system = " ".join(
            message["content"]
            for message in payload["messages"]
            if message["role"] == "system"
        )
        if "NL2SQL" in system:
            content = json.dumps({
                "sql": (
                    "SELECT region_name, SUM(net_revenue) "
                    "FROM orders GROUP BY region_name"
                )
            })
        elif "JSON" in system:
            content = json.dumps({"status": "ok"})
        else:
            content = "一加一等于二。"
        return _json_result(
            {
                "choices": [{"message": {"content": content}}],
                "usage": {"total_tokens": 12},
            }
        )

    report = validate_all_providers(specs, requester=requester)

    assert report["runtime_status"] == "PASS"
    assert report["usable_provider_count"] == 1
    assert report["providers"][0]["final_status"] == "PASS"
    assert secret not in json.dumps(report)


def test_authentication_failure_is_sanitized_and_stops_model_calls(monkeypatch):
    monkeypatch.setattr(
        "app.evaluation.live_model_provider_validation.socket.getaddrinfo",
        lambda *_args: [(None, None, None, None, None)],
    )
    secret = "sk-invalid-secret"
    calls = []

    def requester(method, url, headers, payload, timeout):
        calls.append((method, url))
        return _json_result(
            {"error": {"code": "invalid_authentication_error"}},
            status=401,
        )

    report = validate_all_providers(
        [ProviderSpec("deepseek", "https://example.test", "deepseek-chat", secret)],
        requester=requester,
    )

    assert report["runtime_status"] == "PROVIDER_AUTHENTICATION_FAILED"
    assert report["usable_provider_count"] == 0
    assert report["providers"][0]["checks"]["models"]["http_status"] == 401
    assert calls == [("GET", "https://example.test/models")]
    assert secret not in json.dumps(report)


def test_mimo_rechecks_api_key_header_after_bearer_401(monkeypatch):
    monkeypatch.setattr(
        "app.evaluation.live_model_provider_validation.socket.getaddrinfo",
        lambda *_args: [(None, None, None, None, None)],
    )
    seen_headers = []

    def requester(method, url, headers, payload, timeout):
        seen_headers.append(headers)
        return _json_result({"error": {"code": "401"}}, status=401)

    report = validate_all_providers(
        [
            ProviderSpec(
                "mimo",
                "https://example.test/v1",
                "mimo-v2.5-pro",
                "secret",
            )
        ],
        requester=requester,
    )

    assert report["usable_provider_count"] == 0
    assert len(seen_headers) == 2
    assert "Authorization" in seen_headers[0]
    assert "api-key" in seen_headers[1]


def test_provider_environment_requires_all_runtime_references(monkeypatch):
    for _, base_env, model_env, key_env in (
        ("kimi", "KIMI_BASE_URL", "KIMI_PREFERRED_MODEL", "KIMI_API_KEY"),
        ("mimo", "MIMO_BASE_URL", "MIMO_PREFERRED_MODEL", "MIMO_API_KEY"),
        (
            "deepseek",
            "DEEPSEEK_BASE_URL",
            "DEEPSEEK_PREFERRED_MODEL",
            "DEEPSEEK_API_KEY",
        ),
    ):
        monkeypatch.delenv(base_env, raising=False)
        monkeypatch.delenv(model_env, raising=False)
        monkeypatch.delenv(key_env, raising=False)

    with pytest.raises(RuntimeError, match="runtime references are unavailable"):
        load_provider_specs()


def test_model_selection_prefers_exact_then_provider_family():
    assert select_model(
        ["kimi-k2.5", "kimi-k2.6"],
        "kimi-k2.6",
        "kimi",
    ) == "kimi-k2.6"
    assert select_model(
        ["mimo-v2.5-lite"],
        "missing",
        "mimo",
    ) == "mimo-v2.5-lite"
    assert select_model([], "deepseek-v4-flash", "deepseek") is None
