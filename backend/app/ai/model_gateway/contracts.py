from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TaskType(StrEnum):
    SQLBOT_NL2SQL = "sqlbot_nl2sql"
    RAG_QUERY_REWRITE = "rag_query_rewrite"
    RAG_ANSWER_GENERATION = "rag_answer_generation"
    RESPONSE_COMPOSER = "response_composer"
    FUTURE_MEMORY_SKILL = "future_memory_skill"


class DataClassification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    SIMULATED = "simulated"
    RESTRICTED = "restricted"


class RetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_retries: Literal[0, 1] = 1
    retryable_status_codes: tuple[int, ...] = (408, 429, 500, 502, 503, 504)


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    config_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,63}$")
    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,31}$")
    base_url: str
    model_name: str = Field(min_length=1, max_length=128)
    credential_ref: str | None = Field(default=None, pattern=r"^env://[A-Z][A-Z0-9_]{2,127}$")
    task_type: TaskType
    data_classification: frozenset[DataClassification] = frozenset(
        {DataClassification.PUBLIC, DataClassification.SIMULATED}
    )
    timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    max_tokens: int = Field(default=1024, ge=1, le=32768)
    temperature: float = Field(default=0.0, ge=0, le=2)
    retry_policy: RetryPolicy = RetryPolicy()
    fallback_model: str | None = None
    enabled: bool = False

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        value = value.rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("base_url must use HTTP or HTTPS")
        return value


class GatewayMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=100_000)


class GatewayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_type: TaskType
    messages: tuple[GatewayMessage, ...]
    data_classification: DataClassification = DataClassification.SIMULATED
    trace_id: str = Field(min_length=8, max_length=96)
    run_id: str | None = Field(default=None, max_length=96)
    response_format: Literal["text", "json_object"] = "text"
    metadata: dict[str, Any] = Field(default_factory=dict)


class TokenUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class GatewayResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    content: str
    provider: str
    model_name: str
    task_type: TaskType
    usage: TokenUsage
    latency_ms: int
    attempt_count: int
    fallback_used: bool
    trace_id: str
    run_id: str | None = None
    finish_reason: str | None = None


class ProviderResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    content: str
    usage: TokenUsage = TokenUsage()
    finish_reason: str | None = None
