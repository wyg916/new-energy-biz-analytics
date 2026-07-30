from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any

from app.platform.identity import IdentityContext


@dataclass(frozen=True)
class QueryRequest:
    question: str
    identity_context: IdentityContext
    scenario_id: str
    conversation_state: dict[str, Any] = field(default_factory=dict)
    locale: str = "zh-CN"
    limits: dict[str, int] = field(default_factory=lambda: {"rows": 5000})


@dataclass(frozen=True)
class QueryResult:
    engine: str
    engine_version: str
    scenario: str
    scenario_version: str | None
    semantic_version: str | None
    dataset_version: str | None
    sql: str | None
    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    chart_spec: dict[str, Any] | None
    evidence: dict[str, Any]
    warnings: tuple[str, ...]
    execution_time: int
    trace_id: str
    run_id: str | None
    status: str

    def as_dict(self) -> dict:
        return asdict(self)


class QueryEngine(ABC):
    name: str
    version: str

    @abstractmethod
    def execute(self, request: QueryRequest) -> QueryResult:
        raise NotImplementedError

    @abstractmethod
    def health_check(self) -> dict:
        raise NotImplementedError


class SQLBotEngine(QueryEngine):
    name = "sqlbot"
    version = "placeholder-0.1"

    def __init__(self, enabled: bool = False):
        self.enabled = enabled

    def execute(self, request: QueryRequest) -> QueryResult:
        del request
        raise RuntimeError("NOT_CONFIGURED")

    def health_check(self) -> dict:
        return {
            "engine": self.name,
            "version": self.version,
            "enabled": False,
            "status": "NOT_CONFIGURED",
        }

