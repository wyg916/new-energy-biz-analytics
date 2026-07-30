from datetime import UTC, datetime

from app.core.database import SessionLocal
from app.models.query_routing import (
    QueryRouteDecisionRecord,
    ShadowEvaluation,
    SQLBotSessionBindingRecord,
)
from app.platform.identity import IdentityContext
from app.platform.query_engine import QueryContext, QueryRequest, QueryResult
from app.query_engines.shadow import RoutingEvidenceRepository
from app.query_engines.sqlbot.contracts import SQLBotSession, SQLBotSessionKey


def _identity() -> IdentityContext:
    return IdentityContext(
        subject_id="user:1",
        tenant_id="tenant-a",
        org_id="org-a",
        workspace_id="workspace-a",
        roles=("analyst",),
        groups=(),
        data_scopes=("workspace:all",),
        auth_strength="test",
        issued_at=datetime.now(UTC),
        request_id="trace-shadow-1",
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
        allowed_relations={"semantic_sales": ("sales_revenue",)},
    )


def _result(engine: str) -> QueryResult:
    return QueryResult(
        engine=engine,
        engine_version="test",
        scenario="sales_ops",
        scenario_version="1.0.0",
        semantic_version="1.0.0",
        dataset_version="1",
        sql="SELECT sales_revenue FROM semantic_sales LIMIT 1",
        columns=("sales_revenue",),
        rows=({"sales_revenue": 10},),
        chart_spec=None,
        evidence={
            "query_guard": "passed",
            "metric_values": {"sales_revenue": 10},
        },
        warnings=(),
        execution_time=9,
        trace_id="trace-shadow-1",
        run_id="run-shadow-1",
        status="completed",
    )


def test_shadow_route_and_session_evidence_never_persist_access_token() -> None:
    request = QueryRequest(
        question="销售额",
        identity_context=_identity(),
        scenario_id="sales_ops",
    )
    context = _context()
    with SessionLocal() as db:
        repository = RoutingEvidenceRepository(db)
        session = SQLBotSession(
            key=SQLBotSessionKey(
                tenant_id="tenant-a",
                workspace_id="workspace-a",
                subject_id="user:1",
                conversation_id="conversation-a",
                scenario_id="sales_ops",
                scenario_version="1.0.0",
                semantic_version="1.0.0",
                dataset_version="1",
            ),
            external_chat_id="101",
            access_token="must-never-persist",
        )
        repository.record_session_binding(session)
        repository.record_route(
            request,
            context,
            route_decision="DETERMINISTIC_WITH_SHADOW",
            route_reason="shadow_completed",
            mode="SHADOW",
            engine="deterministic",
            feature_flag_version="p1b-test",
            run_id="run-shadow-1",
        )
        repository.record_shadow(
            request,
            context,
            _result("deterministic"),
            _result("sqlbot"),
            route_mode="SHADOW",
        )

        binding = db.query(SQLBotSessionBindingRecord).one()
        route = db.query(QueryRouteDecisionRecord).one()
        shadow = db.query(ShadowEvaluation).one()
        assert binding.conversation_id == "conversation-a"
        assert binding.external_chat_id == "101"
        assert not hasattr(binding, "access_token")
        assert route.engine == "deterministic"
        assert shadow.execution_accuracy == 1.0
        assert shadow.metric_value_match == 1
        assert shadow.permission_result == "PASS"
