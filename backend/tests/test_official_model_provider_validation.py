import hashlib
import json

import pytest

from app.evaluation.official_model_provider_validation import (
    HttpResult,
    ProviderSpec,
    load_provider_specs,
    parse_env_file,
    validate_all_providers,
)


pytestmark = pytest.mark.no_db


def _result(
    body: dict,
    *,
    status: int = 200,
    request_id: str = "request-test",
) -> HttpResult:
    return HttpResult(
        status_code=status,
        body=json.dumps(body).encode(),
        latency_ms=5,
        headers={"x-request-id": request_id},
        error_type="HTTPError" if status >= 400 else None,
    )


def _completion(content: str, model: str) -> HttpResult:
    return _result({
        "model": model,
        "choices": [{"message": {"content": content}}],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
    })


def _spec(alias: str, base_url: str, model: str) -> ProviderSpec:
    key = "sk-secret-value"
    return ProviderSpec(
        alias=alias,
        base_url=base_url,
        preferred_model=model,
        api_key=key,
        key_fingerprint=hashlib.sha256(key.encode()).hexdigest()[:12],
    )


def test_env_file_parser_handles_bom_quotes_and_safe_audit(tmp_path):
    source = tmp_path / "providers.env"
    source.write_text(
        "\ufeffKIMI_API_KEY=  'sk-kimi'  \n"
        "KIMI_BASE_URL=https://api.moonshot.cn/v1\n"
        "KIMI_MODEL=kimi-k2.6\n"
        'MIMO_API_KEY="sk-mimo"\n'
        "MIMO_BASE_URL=https://api.xiaomimimo.com/v1\n"
        "MIMO_MODEL=mimo-v2.5-pro\n"
        "DEEPSEEK_API_KEY=sk-deepseek\n"
        "DEEPSEEK_BASE_URL=https://api.deepseek.com\n"
        "DEEPSEEK_MODEL=deepseek-v4-flash\n",
        encoding="utf-8",
    )

    values, audit = parse_env_file(source)

    assert values["KIMI_API_KEY"] == "sk-kimi"
    assert values["MIMO_API_KEY"] == "sk-mimo"
    assert audit["bom_present"] is True
    assert audit["duplicates"] == []
    assert audit["fields"]["KIMI_API_KEY"]["prefix"] == "sk-"
    assert len(
        audit["fields"]["KIMI_API_KEY"]["fingerprint_sha256_12"]
    ) == 12
    assert audit["secret_values_exposed"] is False
    assert "sk-kimi" not in json.dumps(audit)


def test_env_file_parser_rejects_duplicate_variables(tmp_path):
    source = tmp_path / "duplicate.env"
    source.write_text(
        "KIMI_API_KEY=sk-first\nKIMI_API_KEY=sk-second\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate environment variables"):
        parse_env_file(source)


def test_official_specs_reject_non_official_base_url():
    values = {
        "KIMI_API_KEY": "sk-kimi",
        "KIMI_BASE_URL": "https://example.test/v1",
        "KIMI_MODEL": "kimi-k2.6",
        "MIMO_API_KEY": "sk-mimo",
        "MIMO_BASE_URL": "https://api.xiaomimimo.com/v1",
        "MIMO_MODEL": "mimo-v2.5-pro",
        "DEEPSEEK_API_KEY": "sk-deepseek",
        "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
        "DEEPSEEK_MODEL": "deepseek-v4-flash",
    }

    with pytest.raises(RuntimeError, match="outside the approved contract"):
        load_provider_specs(values)


def test_kimi_uses_models_bearer_then_three_smokes(monkeypatch):
    monkeypatch.setattr(
        "app.evaluation.official_model_provider_validation.socket.getaddrinfo",
        lambda *_args: [(None, None, None, None, None)],
    )
    calls = []

    def requester(method, url, headers, payload, timeout):
        calls.append((method, url, headers, payload))
        assert headers["Authorization"] == "Bearer sk-secret-value"
        if method == "GET":
            return _result({"data": [{"id": "kimi-k2.6"}]})
        check_index = len([item for item in calls if item[0] == "POST"])
        if check_index == 1:
            assert "temperature" not in payload
            return _completion("OK", "kimi-k2.6")
        if check_index == 2:
            return _completion(
                '{"status":"ok","provider":"kimi"}',
                "kimi-k2.6",
            )
        return _completion(
            "SELECT region, SUM(revenue) AS revenue FROM orders "
            "WHERE order_date >= DATE '2026-01-01' "
            "AND order_date < DATE '2026-02-01' "
            "GROUP BY region ORDER BY revenue DESC",
            "kimi-k2.6",
        )

    report = validate_all_providers(
        [_spec("kimi", "https://api.moonshot.cn/v1", "kimi-k2.6")],
        requester=requester,
    )

    assert report["runtime_status"] == "PASS"
    assert report["providers"][0]["final_status"] == "PASS"
    assert report["providers"][0]["fingerprint_match"] is True
    assert len(calls) == 4
    assert "sk-secret-value" not in json.dumps(report)


def test_deepseek_401_retries_once_and_keeps_request_id(monkeypatch):
    monkeypatch.setattr(
        "app.evaluation.official_model_provider_validation.socket.getaddrinfo",
        lambda *_args: [(None, None, None, None, None)],
    )
    calls = []

    def requester(method, url, headers, payload, timeout):
        calls.append((method, url))
        return _result(
            {"error": {"type": "invalid_request_error"}},
            status=401,
            request_id="deepseek-request",
        )

    report = validate_all_providers(
        [_spec("deepseek", "https://api.deepseek.com", "deepseek-v4-flash")],
        requester=requester,
    )

    provider = report["providers"][0]
    assert provider["checks"]["models"]["attempts"] == 2
    assert provider["checks"]["models"]["request_id"] == "deepseek-request"
    assert calls == [
        ("GET", "https://api.deepseek.com/models"),
        ("GET", "https://api.deepseek.com/models"),
    ]


def test_mimo_calls_chat_with_api_key_without_models(monkeypatch):
    monkeypatch.setattr(
        "app.evaluation.official_model_provider_validation.socket.getaddrinfo",
        lambda *_args: [(None, None, None, None, None)],
    )
    calls = []

    def requester(method, url, headers, payload, timeout):
        calls.append((method, url, headers, payload))
        assert method == "POST"
        assert url.endswith("/chat/completions")
        assert headers["api-key"] == "sk-secret-value"
        assert payload["temperature"] == 1.0
        assert payload["top_p"] == 0.95
        index = len(calls)
        if index == 1:
            return _completion("OK", "mimo-v2.5-pro")
        if index == 2:
            return _completion(
                '{"status":"ok","provider":"mimo"}',
                "mimo-v2.5-pro",
            )
        return _completion(
            "SELECT region, SUM(revenue) AS revenue FROM orders "
            "GROUP BY region ORDER BY revenue DESC",
            "mimo-v2.5-pro",
        )

    report = validate_all_providers(
        [
            _spec(
                "mimo",
                "https://api.xiaomimimo.com/v1",
                "mimo-v2.5-pro",
            )
        ],
        requester=requester,
    )

    provider = report["providers"][0]
    assert provider["final_status"] == "PASS"
    assert provider["auth_method"] == "api-key"
    assert len(calls) == 3


def test_mimo_only_falls_back_to_bearer_after_api_key_401(monkeypatch):
    monkeypatch.setattr(
        "app.evaluation.official_model_provider_validation.socket.getaddrinfo",
        lambda *_args: [(None, None, None, None, None)],
    )
    calls = []

    def requester(method, url, headers, payload, timeout):
        calls.append(headers)
        if len(calls) == 1:
            return _result({"error": {"code": "401"}}, status=401)
        if len(calls) == 2:
            return _completion("OK", "mimo-v2.5-pro")
        if len(calls) == 3:
            return _completion(
                '{"status":"ok","provider":"mimo"}',
                "mimo-v2.5-pro",
            )
        return _completion(
            "SELECT region, SUM(revenue) FROM orders GROUP BY region",
            "mimo-v2.5-pro",
        )

    report = validate_all_providers(
        [
            _spec(
                "mimo",
                "https://api.xiaomimimo.com/v1",
                "mimo-v2.5-pro",
            )
        ],
        requester=requester,
    )

    assert "api-key" in calls[0]
    assert "Authorization" in calls[1]
    assert report["providers"][0]["auth_method"] == "Authorization: Bearer"


def test_all_official_401_results_use_required_blocker(monkeypatch):
    monkeypatch.setattr(
        "app.evaluation.official_model_provider_validation.socket.getaddrinfo",
        lambda *_args: [(None, None, None, None, None)],
    )

    def requester(method, url, headers, payload, timeout):
        return _result({"error": {"code": "401"}}, status=401)

    report = validate_all_providers(
        [
            _spec("kimi", "https://api.moonshot.cn/v1", "kimi-k2.6"),
            _spec(
                "deepseek",
                "https://api.deepseek.com",
                "deepseek-v4-flash",
            ),
            _spec(
                "mimo",
                "https://api.xiaomimimo.com/v1",
                "mimo-v2.5-pro",
            ),
        ],
        requester=requester,
    )

    assert (
        report["runtime_status"]
        == "PROVIDER_CREDENTIALS_REJECTED_BY_OFFICIAL_API"
    )
    assert report["usable_provider_count"] == 0
    assert report["secret_values_exposed"] is False
