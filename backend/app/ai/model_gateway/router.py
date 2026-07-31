import time
from collections import defaultdict
from dataclasses import dataclass

from app.ai.model_gateway.client import ProviderClient
from app.ai.model_gateway.contracts import GatewayRequest, GatewayResponse, ModelConfig, ProviderResult
from app.ai.model_gateway.errors import (
    ModelCircuitOpenError,
    ModelGatewayError,
    ModelNotConfiguredError,
    ModelPolicyDeniedError,
)
from app.ai.model_gateway.registry import ModelRegistry
from app.ai.model_gateway.usage import UsageRecord, UsageRecorder


@dataclass
class _CircuitState:
    failure_count: int = 0
    opened_at: float | None = None


class ModelGateway:
    def __init__(
        self,
        registry: ModelRegistry,
        providers: dict[str, ProviderClient],
        usage: UsageRecorder | None = None,
        *,
        failure_threshold: int = 3,
        recovery_seconds: float = 30.0,
    ) -> None:
        self.registry = registry
        self.providers = providers
        self.usage = usage or UsageRecorder()
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self._circuits: dict[str, _CircuitState] = defaultdict(_CircuitState)

    def complete(self, request: GatewayRequest) -> GatewayResponse:
        primary = self.registry.primary_for(request.task_type)
        attempted: set[str] = set()
        last_error: ModelGatewayError | None = None
        for config, fallback_used in self._route_candidates(primary):
            if config.config_id in attempted:
                continue
            attempted.add(config.config_id)
            try:
                return self._attempt_model(config, request, fallback_used=fallback_used)
            except ModelGatewayError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise ModelNotConfiguredError("no model route is available")

    def _route_candidates(self, primary: ModelConfig):
        yield primary, False
        if primary.fallback_model:
            fallback = self.registry.get(primary.fallback_model)
            if fallback.enabled:
                yield fallback, True

    def _attempt_model(
        self,
        config: ModelConfig,
        request: GatewayRequest,
        *,
        fallback_used: bool,
    ) -> GatewayResponse:
        if request.data_classification not in config.data_classification:
            raise ModelPolicyDeniedError("data classification is not allowed for this model")
        provider = self.providers.get(config.provider)
        if provider is None:
            raise ModelNotConfiguredError("provider client is not registered")
        self._assert_circuit(config.config_id)
        started = time.perf_counter()
        attempts = 0
        last_error: ModelGatewayError | None = None
        max_attempts = 1 + config.retry_policy.max_retries
        while attempts < max_attempts:
            attempts += 1
            try:
                result = provider.complete(config, request)
                self._circuits[config.config_id] = _CircuitState()
                latency_ms = max(0, int((time.perf_counter() - started) * 1000))
                self._record_success(config, request, result, latency_ms, attempts, fallback_used)
                return GatewayResponse(
                    content=result.content,
                    provider=config.provider,
                    model_name=config.model_name,
                    task_type=request.task_type,
                    usage=result.usage,
                    latency_ms=latency_ms,
                    attempt_count=attempts,
                    fallback_used=fallback_used,
                    trace_id=request.trace_id,
                    run_id=request.run_id,
                    finish_reason=result.finish_reason,
                )
            except ModelGatewayError as exc:
                last_error = exc
                if not exc.retryable or attempts >= max_attempts:
                    break
        latency_ms = max(0, int((time.perf_counter() - started) * 1000))
        self._record_failure(config, request, last_error, latency_ms, attempts, fallback_used)
        state = self._circuits[config.config_id]
        state.failure_count += 1
        if state.failure_count >= self.failure_threshold:
            state.opened_at = time.monotonic()
        assert last_error is not None
        raise last_error

    def _assert_circuit(self, config_id: str) -> None:
        state = self._circuits[config_id]
        if state.opened_at is None:
            return
        if time.monotonic() - state.opened_at >= self.recovery_seconds:
            self._circuits[config_id] = _CircuitState()
            return
        raise ModelCircuitOpenError("model route circuit is open")

    def _record_success(
        self,
        config: ModelConfig,
        request: GatewayRequest,
        result: ProviderResult,
        latency_ms: int,
        attempts: int,
        fallback_used: bool,
    ) -> None:
        self.usage.record(UsageRecord(
            config_id=config.config_id,
            provider=config.provider,
            model_name=config.model_name,
            task_type=request.task_type,
            outcome="SUCCESS",
            prompt_tokens=result.usage.prompt_tokens,
            completion_tokens=result.usage.completion_tokens,
            total_tokens=result.usage.total_tokens,
            latency_ms=latency_ms,
            attempt_count=attempts,
            fallback_used=fallback_used,
            trace_id=request.trace_id,
            run_id=request.run_id,
            error_code=None,
            created_at=self.usage.now(),
        ))

    def _record_failure(
        self,
        config: ModelConfig,
        request: GatewayRequest,
        error: ModelGatewayError | None,
        latency_ms: int,
        attempts: int,
        fallback_used: bool,
    ) -> None:
        self.usage.record(UsageRecord(
            config_id=config.config_id,
            provider=config.provider,
            model_name=config.model_name,
            task_type=request.task_type,
            outcome="FAILED",
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            latency_ms=latency_ms,
            attempt_count=attempts,
            fallback_used=fallback_used,
            trace_id=request.trace_id,
            run_id=request.run_id,
            error_code=error.code if error else "MODEL_GATEWAY_ERROR",
            created_at=self.usage.now(),
        ))
