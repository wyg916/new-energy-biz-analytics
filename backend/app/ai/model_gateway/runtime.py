from functools import lru_cache

from app.ai.model_gateway.client import DeepSeekProvider, KimiProvider, MiMoProvider
from app.ai.model_gateway.contracts import (
    DataClassification,
    ModelConfig,
    TaskType,
)
from app.ai.model_gateway.registry import ModelRegistry
from app.ai.model_gateway.router import ModelGateway
from app.core.config import get_settings


def _config(
    config_id: str,
    *,
    base_url: str,
    model_name: str,
    credential_ref: str,
    enabled: bool,
    fallback_model: str | None,
    provider: str,
) -> ModelConfig | None:
    if not base_url or not model_name:
        return None
    return ModelConfig(
        config_id=config_id,
        provider=provider,
        base_url=base_url,
        model_name=model_name,
        credential_ref=credential_ref,
        task_type=TaskType.RAG_ANSWER_GENERATION,
        data_classification=frozenset({
            DataClassification.PUBLIC,
            DataClassification.SIMULATED,
        }),
        timeout_seconds=20,
        max_tokens=1200,
        temperature=0,
        fallback_model=fallback_model,
        enabled=enabled,
    )


@lru_cache
def get_runtime_model_gateway() -> ModelGateway:
    settings = get_settings()
    candidates = [
        _config(
            "kimi-rag-primary",
            base_url=settings.model_gateway_kimi_base_url,
            model_name=settings.model_gateway_kimi_model_name,
            credential_ref=settings.model_gateway_kimi_credential_ref,
            enabled=settings.model_gateway_kimi_enabled,
            fallback_model="mimo-rag-standby",
            provider="kimi",
        ),
        _config(
            "mimo-rag-standby",
            base_url=settings.model_gateway_mimo_base_url,
            model_name=settings.model_gateway_mimo_model_name,
            credential_ref=settings.model_gateway_mimo_credential_ref,
            enabled=settings.model_gateway_mimo_enabled,
            fallback_model=None,
            provider="mimo",
        ),
        _config(
            "deepseek-rag-fallback",
            base_url=settings.model_gateway_deepseek_base_url,
            model_name=settings.model_gateway_deepseek_model_name,
            credential_ref=settings.model_gateway_deepseek_credential_ref,
            enabled=settings.model_gateway_deepseek_enabled,
            fallback_model=None,
            provider="deepseek",
        ),
    ]
    registry = ModelRegistry([item for item in candidates if item is not None])
    return ModelGateway(
        registry,
        {
            "kimi": KimiProvider(),
            "mimo": MiMoProvider(),
            "deepseek": DeepSeekProvider(),
        },
    )


def runtime_model_status() -> dict:
    settings = get_settings()
    providers = [
        {
            "provider_alias": "kimi",
            "configured": bool(
                settings.model_gateway_kimi_base_url
                and settings.model_gateway_kimi_model_name
            ),
            "enabled": settings.model_gateway_kimi_enabled,
            "credential_ref": settings.model_gateway_kimi_credential_ref,
        },
        {
            "provider_alias": "mimo",
            "configured": bool(
                settings.model_gateway_mimo_base_url
                and settings.model_gateway_mimo_model_name
            ),
            "enabled": settings.model_gateway_mimo_enabled,
            "credential_ref": settings.model_gateway_mimo_credential_ref,
        },
        {
            "provider_alias": "deepseek",
            "configured": bool(
                settings.model_gateway_deepseek_base_url
                and settings.model_gateway_deepseek_model_name
            ),
            "enabled": settings.model_gateway_deepseek_enabled,
            "credential_ref": settings.model_gateway_deepseek_credential_ref,
        },
    ]
    ready = any(item["configured"] and item["enabled"] for item in providers)
    return {
        "status": "READY" if ready else "MODEL_RUNTIME_PENDING",
        "providers": providers,
        "secret_values_exposed": False,
    }
