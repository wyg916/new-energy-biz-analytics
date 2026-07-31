from app.ai.model_gateway.client import ProviderClient
from app.ai.model_gateway.registry import ModelRegistry


def model_health_snapshot(
    registry: ModelRegistry,
    providers: dict[str, ProviderClient],
) -> list[dict]:
    result: list[dict] = []
    for item in registry.safe_snapshot():
        provider = providers.get(item["provider"])
        healthy = bool(provider and item["enabled"] and provider.health(registry.get(item["config_id"])))
        result.append({
            "config_id": item["config_id"],
            "provider": item["provider"],
            "model_name": item["model_name"],
            "task_type": item["task_type"],
            "enabled": item["enabled"],
            "healthy": healthy,
        })
    return result
