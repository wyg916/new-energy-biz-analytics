from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.platform.identity import IdentityContext
from app.platform.query_engine import (
    QueryContext,
    QueryEngine,
    QueryRequest,
    QueryResult,
)
from app.query_engines.router import (
    CanaryPolicy,
    EngineMode,
    EngineRouter,
    QueryRoutingError,
)
from app.query_engines.sqlbot.error_mapper import (
    SQLBotEngineError,
    SQLBotErrorCode,
)

pytestmark = pytest.mark.no_db


class FakeEngine(QueryEngine):
    version = "test-1"

    def __init__(self, name: str, result: QueryResult | None = None, error=None):
        self.name = name
        self.result = result
        self.error = error
        self.calls = 0

    def execute(self, request, context=None):
        del request, context
        self.calls += 1
        if self.error:
            raise self.error
        assert self.result is not None
        return self.result

    def health_check(self):
        return {"status": "ok"}


def _identity() -> IdentityContext:
    return IdentityContext(
        subject_id="user:canary",
        tenant_id="tenant-a",
        org_id="org-a",
        workspace_id="workspace-a",
        roles=("analyst",),
        groups=(),
        data_scopes=("workspace:all",),
        auth_strength="test",
        issued_at=datetime.now(UTC),
        request_id="request-router-1",
    )


def _request() -> QueryRequest:
    return QueryRequest(
        question="按区域查看销售额",
        identity_context=_identity(),
        scenario_id="sales_ops",
    )


def _context() -> QueryContext:
    return QueryContext(
        conversation_id="conversation-a",
        scenario_version="1.0.0",
        semantic_version="1.0.0",
        semantic_model_version_id="semantic-a",
        dataset_version="1",
        dataset_version_id="dataset-a",
        datasource_id="42",
        allowed_relations={"semantic_sales": ("region", "sales_revenue")},
        max_rows=100,
    )


def _result(engine: str, value: int = 10) -> QueryResult:
    return QueryResult(
        engine=engine,
        engine_version="test-1",
        scenario="sales_ops",
        scenario_version="1.0.0",
        semantic_version="1.0.0",
        dataset_version="1",
        sql=f"SELECT region, sales_revenue FROM semantic_sales LIMIT 10",
        columns=("region", "sales_revenue"),
        rows=({"region": "north", "sales_revenue": value},),
        chart_spec=None,
        evidence={
            "query_guard": "passed",
            "metric_values": {"sales_revenue": value},
            "time_range": ["2026-01-01", "2026-07-01"],
            "dimensions": ["region"],
        },
        warnings=(),
        execution_time=10,
        trace_id="request-router-1",
        run_id=f"run-{engine}",
        status="completed",
    )


def test_deterministic_only_never_calls_sqlbot() -> None:
    deterministic = FakeEngine("deterministic", _result("deterministic"))
    sqlbot = FakeEngine("sqlbot", _result("sqlbot"))
    routed = EngineRouter(
        deterministic,
        sqlbot,
        mode=EngineMode.DETERMINISTIC_ONLY,
    ).execute(_request(), _context(), deterministic_supported=False)
    assert routed.result.engine == "deterministic"
    assert routed.route_decision == "DETERMINISTIC_ONLY"
    assert deterministic.calls == 1
    assert sqlbot.calls == 0


def test_shadow_returns_deterministic_and_compares_sqlbot() -> None:
    deterministic = FakeEngine("deterministic", _result("deterministic"))
    sqlbot = FakeEngine("sqlbot", _result("sqlbot"))
    routed = EngineRouter(
        deterministic,
        sqlbot,
        mode=EngineMode.SHADOW,
    ).execute(_request(), _context(), deterministic_supported=True)
    assert routed.result.engine == "deterministic"
    assert routed.route_decision == "DETERMINISTIC_WITH_SHADOW"
    assert routed.shadow_comparison is not None
    assert routed.shadow_comparison.execution_accuracy == 1.0
    assert deterministic.calls == sqlbot.calls == 1


def test_sqlbot_failure_does_not_affect_shadow_user_result() -> None:
    deterministic = FakeEngine("deterministic", _result("deterministic"))
    sqlbot = FakeEngine(
        "sqlbot",
        error=SQLBotEngineError(
            SQLBotErrorCode.RUNTIME_PENDING,
            "runtime pending",
        ),
    )
    routed = EngineRouter(
        deterministic,
        sqlbot,
        mode=EngineMode.SHADOW,
    ).execute(_request(), _context(), deterministic_supported=True)
    assert routed.result.engine == "deterministic"
    assert routed.result.warnings == ("SQLBOT_RUNTIME_PENDING",)
    assert routed.route_reason == "SQLBOT_RUNTIME_PENDING"


def test_canary_routes_only_selected_long_tail_queries() -> None:
    deterministic = FakeEngine("deterministic", _result("deterministic"))
    sqlbot = FakeEngine("sqlbot", _result("sqlbot"))
    selected = EngineRouter(
        deterministic,
        sqlbot,
        mode=EngineMode.CANARY,
        canary=CanaryPolicy(
            percentage=100,
            tenants=frozenset({"tenant-a"}),
            workspaces=frozenset({"workspace-a"}),
            users=frozenset({"user:canary"}),
            scenarios=frozenset({"sales_ops"}),
        ),
    ).execute(_request(), _context(), deterministic_supported=False)
    assert selected.result.engine == "sqlbot"
    assert selected.route_decision == "SQLBOT_CANARY"

    with pytest.raises(QueryRoutingError) as rejected:
        EngineRouter(
            deterministic,
            sqlbot,
            mode=EngineMode.CANARY,
            canary=CanaryPolicy(
                percentage=0,
                tenants=frozenset({"tenant-a"}),
                workspaces=frozenset({"workspace-a"}),
                users=frozenset({"user:canary"}),
                scenarios=frozenset({"sales_ops"}),
            ),
        ).execute(_request(), _context(), deterministic_supported=False)
    assert rejected.value.code == "CANARY_NOT_SELECTED"


@pytest.mark.parametrize("missing", ("tenants", "workspaces", "users", "scenarios"))
def test_canary_requires_all_four_allowlists(missing: str) -> None:
    scope = {
        "tenants": frozenset({"tenant-a"}),
        "workspaces": frozenset({"workspace-a"}),
        "users": frozenset({"user:canary"}),
        "scenarios": frozenset({"sales_ops"}),
    }
    scope[missing] = frozenset()
    with pytest.raises(ValueError, match="requires tenant, workspace, user, and scenario"):
        EngineRouter(
            FakeEngine("deterministic", _result("deterministic")),
            FakeEngine("sqlbot", _result("sqlbot")),
            mode=EngineMode.CANARY,
            canary=CanaryPolicy(percentage=5, **scope),
        )


def test_core_query_remains_deterministic_even_when_sqlbot_enabled() -> None:
    deterministic = FakeEngine("deterministic", _result("deterministic"))
    sqlbot = FakeEngine("sqlbot", _result("sqlbot"))
    routed = EngineRouter(
        deterministic,
        sqlbot,
        mode=EngineMode.SQLBOT_ENABLED,
    ).execute(_request(), _context(), deterministic_supported=True)
    assert routed.result.engine == "deterministic"
    assert routed.route_reason == "core_query_pinned"
    assert sqlbot.calls == 0


def test_disabled_mode_fails_closed() -> None:
    router = EngineRouter(
        FakeEngine("deterministic", _result("deterministic")),
        FakeEngine("sqlbot", _result("sqlbot")),
        mode=EngineMode.DISABLED,
    )
    with pytest.raises(QueryRoutingError) as exc:
        router.execute(_request(), _context(), deterministic_supported=False)
    assert exc.value.code == "QUERY_ENGINE_DISABLED"


@pytest.mark.parametrize("configured_mode", ("SHADOW", "CANARY", "SCOPED_STABLE"))
def test_sqlbot_enabled_false_is_a_single_switch_emergency_fallback(
    configured_mode: str,
) -> None:
    deterministic = FakeEngine("deterministic", _result("deterministic"))
    sqlbot = FakeEngine("sqlbot", _result("sqlbot"))
    settings = SimpleNamespace(
        effective_query_engine_mode=configured_mode,
        sqlbot_engine_enabled=False,
        query_engine_canary_scope={
            "tenants": frozenset({"tenant-a"}),
            "workspaces": frozenset({"workspace-a"}),
            "users": frozenset({"user:canary"}),
            "scenarios": frozenset({"sales_ops"}),
        },
        query_engine_canary_percentage=20.0,
        query_engine_feature_flag_version="sqlbot-4.1d-test",
        query_engine_auto_fallback_enabled=True,
    )
    with patch("app.query_engines.router.get_settings", return_value=settings):
        routed = EngineRouter.from_settings(deterministic, sqlbot).execute(
            _request(), _context(), deterministic_supported=False
        )
    assert routed.route_decision == "DETERMINISTIC_ONLY"
    assert deterministic.calls == 1
    assert sqlbot.calls == 0
