from collections.abc import Callable
from time import perf_counter

from app.platform.query_engine import QueryEngine, QueryRequest, QueryResult
from app.platform.semantic_registry import ActiveSemanticContext


def _rows_and_columns(result: object) -> tuple[tuple[str, ...], tuple[dict, ...]]:
    if not isinstance(result, dict):
        return (), ()
    if isinstance(result.get("rows"), list):
        rows = tuple(item for item in result["rows"] if isinstance(item, dict))
    elif isinstance(result.get("metrics"), dict):
        rows = (result["metrics"],)
    elif isinstance(result.get("current"), dict):
        rows = (result["current"],)
    elif isinstance(result.get("series"), list):
        rows = tuple(item for item in result["series"] if isinstance(item, dict))
    else:
        rows = ()
    columns = tuple(rows[0]) if rows else ()
    return columns, rows


class DeterministicEngine(QueryEngine):
    name = "deterministic"
    version = "0.1.0"

    def __init__(
        self,
        handler: Callable[[str], dict],
        context: ActiveSemanticContext | None,
    ):
        self.handler = handler
        self.context = context
        self.legacy_response: dict | None = None

    def execute(self, request: QueryRequest) -> QueryResult:
        started = perf_counter()
        response = self.handler(request.question)
        self.legacy_response = response
        evidence = dict(response.get("evidence") or {})
        columns, rows = _rows_and_columns(response.get("result"))
        context = self.context
        warnings = () if context else ("PLATFORM_VERSION_ROUTING_DISABLED",)
        return QueryResult(
            engine=self.name,
            engine_version=self.version,
            scenario=context.scenario_id if context else request.scenario_id,
            scenario_version=context.scenario_version if context else evidence.get("scenario_version"),
            semantic_version=context.semantic_version if context else "legacy-0.1.0",
            dataset_version=str(context.dataset_version) if context else "legacy-platform-facts",
            sql=evidence.get("sql"),
            columns=columns,
            rows=rows,
            chart_spec=response.get("chart"),
            evidence=evidence,
            warnings=warnings,
            execution_time=int((perf_counter() - started) * 1000),
            trace_id=request.identity_context.request_id,
            run_id=evidence.get("analysis_run_id"),
            status=response.get("status", "failed"),
        )

    def health_check(self) -> dict:
        return {
            "engine": self.name,
            "version": self.version,
            "enabled": True,
            "status": "ok",
        }

