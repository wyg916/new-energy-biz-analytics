import json
from collections.abc import Callable
from dataclasses import dataclass
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


@dataclass(frozen=True)
class OpenAIProviderProfile:
    auth_header: str = "Authorization"
    auth_prefix: str = "Bearer "
    max_tokens_field: str = "max_tokens"
    system_message: str | None = None
    extra_body: dict | None = None
    fixed_temperature: float | None = None


class OpenAICompatibleProvider:
    def __init__(
        self,
        credential_resolver: CredentialResolver | None = None,
        transport: httpx.BaseTransport | None = None,
        profile: OpenAIProviderProfile | None = None,
    ) -> None:
        self._credentials = credential_resolver or CredentialResolver()
        self._transport = transport
        self._profile = profile or OpenAIProviderProfile()

    def complete(self, config: ModelConfig, request: GatewayRequest) -> ProviderResult:
        credential = self._credentials.resolve(config.credential_ref)
        headers = {"Content-Type": "application/json"}
        if credential is not None:
            headers[self._profile.auth_header] = (
                f"{self._profile.auth_prefix}{credential.value}"
            )
        messages = [message.model_dump() for message in request.messages]
        if self._profile.system_message:
            messages.insert(0, {
                "role": "system",
                "content": self._profile.system_message,
            })
        payload: dict = {
            "model": config.model_name,
            "messages": messages,
            "temperature": (
                self._profile.fixed_temperature
                if self._profile.fixed_temperature is not None
                else config.temperature
            ),
            self._profile.max_tokens_field: config.max_tokens,
        }
        if self._profile.extra_body:
            payload.update(self._profile.extra_body)
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
            headers = (
                {
                    self._profile.auth_header:
                        f"{self._profile.auth_prefix}{credential.value}"
                }
                if credential else {}
            )
            with httpx.Client(
                timeout=min(config.timeout_seconds, 5.0),
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                response = client.get(f"{config.base_url}/models", headers=headers)
            return response.status_code < 500
        except Exception:
            return False


class KimiProvider(OpenAICompatibleProvider):
    def __init__(self, **kwargs) -> None:
        super().__init__(profile=OpenAIProviderProfile(
            extra_body={"thinking": {"type": "disabled"}},
            fixed_temperature=0.6,
        ), **kwargs)


class MiMoProvider(OpenAICompatibleProvider):
    def __init__(self, **kwargs) -> None:
        super().__init__(profile=OpenAIProviderProfile(
            auth_header="api-key",
            auth_prefix="",
            max_tokens_field="max_completion_tokens",
            system_message=(
                "你是MiMo（中文名称也是MiMo），是小米公司研发的AI智能助手。"
            ),
            extra_body={"thinking": {"type": "disabled"}, "top_p": 0.95},
            fixed_temperature=1.0,
        ), **kwargs)


class DeepSeekProvider(OpenAICompatibleProvider):
    def __init__(self, **kwargs) -> None:
        super().__init__(profile=OpenAIProviderProfile(
            extra_body={"thinking": {"type": "disabled"}},
        ), **kwargs)


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
