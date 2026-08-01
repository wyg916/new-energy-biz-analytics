from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

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
class QueryContext:
    conversation_id: str
    scenario_version: str
    semantic_version: str
    semantic_model_version_id: str
    dataset_version: str
    dataset_version_id: str
    datasource_id: str | None
    allowed_relations: dict[str, tuple[str, ...]]
    prompt_context: dict[str, Any] = field(default_factory=dict)
    execution_mode: str = "upstream_readonly"
    run_id: str | None = None
    max_rows: int = 500
    cancelled: Callable[[], bool] | None = field(
        default=None, repr=False, compare=False
    )


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
    def execute(
        self,
        request: QueryRequest,
        context: QueryContext | None = None,
    ) -> QueryResult:
        raise NotImplementedError

    @abstractmethod
    def health_check(self) -> dict:
        raise NotImplementedError


def __getattr__(name: str):
    """Keep the P1A compatibility export without creating an import cycle."""
    if name == "SQLBotEngine":
        from app.query_engines.sqlbot.engine import SQLBotEngine

        return SQLBotEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
