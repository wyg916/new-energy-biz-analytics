import json
import os

import httpx
import pytest

from app.ai.model_gateway.client import (
    DeepSeekProvider,
    KimiProvider,
    MiMoProvider,
    MockProvider,
    OpenAICompatibleProvider,
)
from app.ai.model_gateway.contracts import (
    DataClassification,
    GatewayMessage,
    GatewayRequest,
    ModelConfig,
    ProviderResult,
    RetryPolicy,
    TaskType,
    TokenUsage,
)
from app.ai.model_gateway.credentials import CredentialResolver
from app.ai.model_gateway.errors import (
    CredentialUnavailableError,
    ModelPolicyDeniedError,
    ModelProviderError,
)
from app.ai.model_gateway.registry import ModelRegistry
from app.ai.model_gateway.router import ModelGateway

pytestmark = pytest.mark.no_db


def config(
    config_id: str,
    *,
    provider: str = "mock",
    fallback_model: str | None = None,
    classifications: frozenset[DataClassification] | None = None,
) -> ModelConfig:
    return ModelConfig(
        config_id=config_id,
        provider=provider,
        base_url="https://model.invalid/v1",
        model_name=f"{config_id}-model",
        task_type=TaskType.RAG_ANSWER_GENERATION,
        credential_ref=None,
        data_classification=classifications or frozenset({DataClassification.SIMULATED}),
        retry_policy=RetryPolicy(max_retries=1),
        fallback_model=fallback_model,
        enabled=True,
    )


def request(classification: DataClassification = DataClassification.SIMULATED) -> GatewayRequest:
    return GatewayRequest(
        task_type=TaskType.RAG_ANSWER_GENERATION,
        messages=(GatewayMessage(role="user", content="contract test"),),
        data_classification=classification,
        trace_id="trace-model-gateway",
        run_id="run-model-gateway",
    )


def test_mock_provider_contract_records_usage() -> None:
    registry = ModelRegistry([config("primary")])
    gateway = ModelGateway(registry, {"mock": MockProvider()})

    result = gateway.complete(request())

    assert result.content == "mock-contract-response"
    assert result.usage.total_tokens == 2
    assert result.attempt_count == 1
    assert gateway.usage.snapshot()[0].outcome == "SUCCESS"


def test_retry_once_then_fallback() -> None:
    attempts = {"count": 0}

    def fail(_config, _request):
        attempts["count"] += 1
        raise ModelProviderError("failed", retryable=True)

    registry = ModelRegistry([
        config("primary", provider="failing", fallback_model="fallback"),
        config("fallback", provider="healthy"),
    ])
    gateway = ModelGateway(
        registry,
        {
            "failing": MockProvider(fail),
            "healthy": MockProvider(lambda _c, _r: ProviderResult(
                content="fallback-result",
                usage=TokenUsage(total_tokens=4),
            )),
        },
    )

    result = gateway.complete(request())

    assert attempts["count"] == 2
    assert result.fallback_used is True
    assert result.content == "fallback-result"
    assert [item.outcome for item in gateway.usage.snapshot()] == ["FAILED", "SUCCESS"]


def test_data_classification_denied_before_provider_call() -> None:
    gateway = ModelGateway(
        ModelRegistry([config("primary")]),
        {"mock": MockProvider()},
    )

    with pytest.raises(ModelPolicyDeniedError):
        gateway.complete(request(DataClassification.RESTRICTED))


def test_credential_reference_does_not_reveal_secret(monkeypatch) -> None:
    monkeypatch.setenv("MODEL_TEST_SECRET", "do-not-reveal-this-value")
    resolved = CredentialResolver().resolve("env://MODEL_TEST_SECRET")

    assert "do-not-reveal" not in repr(resolved)
    monkeypatch.delenv("MODEL_TEST_SECRET")
    with pytest.raises(CredentialUnavailableError) as exc_info:
        CredentialResolver().resolve("env://MODEL_TEST_SECRET")
    assert "MODEL_TEST_SECRET" not in str(exc_info.value)


def test_openai_compatible_response_and_authorization_header(monkeypatch) -> None:
    monkeypatch.setenv("MODEL_TEST_SECRET", "runtime-secret")

    def handler(http_request: httpx.Request) -> httpx.Response:
        assert http_request.headers["Authorization"] == "Bearer runtime-secret"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            },
        )

    provider = OpenAICompatibleProvider(transport=httpx.MockTransport(handler))
    model = config("primary", provider="openai-compatible").model_copy(
        update={"credential_ref": "env://MODEL_TEST_SECRET"}
    )

    result = provider.complete(model, request())

    assert result.content == "ok"
    assert result.usage.total_tokens == 3
    monkeypatch.delenv("MODEL_TEST_SECRET")


@pytest.mark.parametrize(
    ("provider_factory", "expected_thinking"),
    [(KimiProvider, True), (DeepSeekProvider, True)],
)
def test_bearer_provider_adapters_disable_thinking(
    monkeypatch, provider_factory, expected_thinking
) -> None:
    monkeypatch.setenv("MODEL_TEST_SECRET", "runtime-secret")

    def handler(http_request: httpx.Request) -> httpx.Response:
        payload = json.loads(http_request.content)
        assert http_request.headers["Authorization"] == "Bearer runtime-secret"
        assert (payload.get("thinking") == {"type": "disabled"}) is expected_thinking
        assert payload["max_tokens"] == 1024
        if provider_factory is KimiProvider:
            assert payload["temperature"] == 0.6
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {},
        })

    provider = provider_factory(transport=httpx.MockTransport(handler))
    model = config("primary", provider="kimi").model_copy(
        update={"credential_ref": "env://MODEL_TEST_SECRET"}
    )
    assert provider.complete(model, request()).content == "ok"


def test_mimo_adapter_uses_api_key_and_completion_token_contract(monkeypatch) -> None:
    monkeypatch.setenv("MODEL_TEST_SECRET", "runtime-secret")

    def handler(http_request: httpx.Request) -> httpx.Response:
        payload = json.loads(http_request.content)
        assert http_request.headers["api-key"] == "runtime-secret"
        assert "Authorization" not in http_request.headers
        assert payload["max_completion_tokens"] == 1024
        assert "max_tokens" not in payload
        assert payload["messages"][0]["role"] == "system"
        assert "MiMo" in payload["messages"][0]["content"]
        assert payload["temperature"] == 1.0
        assert payload["top_p"] == 0.95
        assert payload["thinking"] == {"type": "disabled"}
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {},
        })

    provider = MiMoProvider(transport=httpx.MockTransport(handler))
    model = config("primary", provider="mimo").model_copy(
        update={"credential_ref": "env://MODEL_TEST_SECRET"}
    )
    assert provider.complete(model, request()).content == "ok"
