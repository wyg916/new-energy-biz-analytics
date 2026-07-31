from collections import defaultdict

from app.ai.model_gateway.contracts import ModelConfig, TaskType
from app.ai.model_gateway.errors import ModelNotConfiguredError


class ModelRegistry:
    def __init__(self, configs: list[ModelConfig] | None = None) -> None:
        self._configs: dict[str, ModelConfig] = {}
        self._task_models: dict[TaskType, list[str]] = defaultdict(list)
        for config in configs or []:
            self.register(config)

    def register(self, config: ModelConfig) -> None:
        if config.config_id in self._configs:
            previous = self._configs[config.config_id]
            self._task_models[previous.task_type] = [
                item for item in self._task_models[previous.task_type] if item != config.config_id
            ]
        self._configs[config.config_id] = config
        self._task_models[config.task_type].append(config.config_id)

    def get(self, config_id: str) -> ModelConfig:
        config = self._configs.get(config_id)
        if config is None:
            raise ModelNotConfiguredError("requested model configuration does not exist")
        return config

    def primary_for(self, task_type: TaskType) -> ModelConfig:
        for config_id in self._task_models.get(task_type, []):
            config = self._configs[config_id]
            if config.enabled:
                return config
        raise ModelNotConfiguredError(f"no enabled model for task {task_type}")

    def safe_snapshot(self) -> list[dict]:
        return [
            {
                "config_id": config.config_id,
                "provider": config.provider,
                "base_url": config.base_url,
                "model_name": config.model_name,
                "credential_ref": config.credential_ref,
                "task_type": config.task_type,
                "data_classification": sorted(config.data_classification),
                "timeout_seconds": config.timeout_seconds,
                "max_tokens": config.max_tokens,
                "temperature": config.temperature,
                "fallback_model": config.fallback_model,
                "enabled": config.enabled,
            }
            for config in self._configs.values()
        ]
