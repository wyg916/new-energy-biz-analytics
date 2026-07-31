import json
from collections.abc import Callable
from typing import Protocol

import httpx

from app.ai.model_gateway.contracts import (
    GatewayRequest,
    ModelConfig,
    ProviderResult,
    TokenUsage,
)
from app.ai.model_gateway.credentials import CredentialResolver
from app.ai.model_gateway.errors import (
    ModelProviderError,
    ModelTimeoutError,
    ModelTransportError,
)


class ProviderClient(Protocol):
    def complete(self, config: ModelConfig, request: GatewayRequest) -> ProviderResult: ...

    def health(self, config: ModelConfig) -> bool: ...


class OpenAICompatibleProvider:
    def __init__(
        self,
        credential_resolver: CredentialResolver | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._credentials = credential_resolver or CredentialResolver()
        self._transport = transport

    def complete(self, config: ModelConfig, request: GatewayRequest) -> ProviderResult:
        credential = self._credentials.resolve(config.credential_ref)
        headers = {"Content-Type": "application/json"}
        if credential is not None:
            headers["Authorization"] = f"Bearer {credential.value}"
        payload: dict = {
            "model": config.model_name,
            "messages": [message.model_dump() for message in request.messages],
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
        }
        if request.response_format == "json_object":
            payload["response_format"] = {"type": "json_object"}
        try:
            with httpx.Client(
                timeout=config.timeout_seconds,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                response = client.post(
                    f"{config.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise ModelTimeoutError("provider request timed out", provider=config.provider) from exc
        except httpx.TransportError as exc:
            raise ModelTransportError("provider transport failed", provider=config.provider) from exc
        if response.status_code >= 400:
            raise ModelProviderError(
                "provider returned an unsuccessful status",
                provider=config.provider,
                retryable=response.status_code in config.retry_policy.retryable_status_codes,
                status_code=response.status_code,
            )
        try:
            body = response.json()
            choice = body["choices"][0]
            usage = body.get("usage") or {}
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ModelProviderError(
                "provider returned an invalid OpenAI-compatible response",
                provider=config.provider,
            ) from exc
        return ProviderResult(
            content=str(content),
            finish_reason=choice.get("finish_reason"),
            usage=TokenUsage(
                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                completion_tokens=int(usage.get("completion_tokens", 0)),
                total_tokens=int(usage.get("total_tokens", 0)),
            ),
        )

    def health(self, config: ModelConfig) -> bool:
        try:
            credential = self._credentials.resolve(config.credential_ref)
            headers = {"Authorization": f"Bearer {credential.value}"} if credential else {}
            with httpx.Client(
                timeout=min(config.timeout_seconds, 5.0),
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                response = client.get(f"{config.base_url}/models", headers=headers)
            return response.status_code < 500
        except Exception:
            return False


class MockProvider:
    """Contract-test provider. Runtime registration must never use this provider."""

    def __init__(
        self,
        responder: Callable[[ModelConfig, GatewayRequest], ProviderResult] | None = None,
    ) -> None:
        self._responder = responder or (
            lambda _config, _request: ProviderResult(
                content="mock-contract-response",
                usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                finish_reason="stop",
            )
        )

    def complete(self, config: ModelConfig, request: GatewayRequest) -> ProviderResult:
        return self._responder(config, request)

    def health(self, config: ModelConfig) -> bool:
        return True
