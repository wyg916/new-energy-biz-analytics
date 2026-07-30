from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class SQLBotSessionKey:
    tenant_id: str
    workspace_id: str
    subject_id: str
    conversation_id: str
    scenario_id: str
    scenario_version: str
    semantic_version: str
    dataset_version: str

    def as_tuple(self) -> tuple[str, ...]:
        return (
            self.tenant_id,
            self.workspace_id,
            self.subject_id,
            self.conversation_id,
            self.scenario_id,
            self.scenario_version,
            self.semantic_version,
            self.dataset_version,
        )


@dataclass
class SQLBotSession:
    key: SQLBotSessionKey
    external_chat_id: str
    access_token: str = field(repr=False)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_used_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    generation: int = 1


@dataclass(frozen=True)
class SQLBotParsedResponse:
    sql: str
    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    chart_spec: dict[str, Any] | None
    token_usage: int | None
    upstream_record_id: str | None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class SQLBotHealth:
    status: str
    latency_ms: int | None = None
    detail: str | None = None
