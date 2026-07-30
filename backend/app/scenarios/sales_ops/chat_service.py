import json
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.auth import User
from app.models.business import SessionState
from app.platform.identity import IdentityContextFactory
from app.platform.query_engine import QueryRequest, QueryResult
from app.query_engines.context import build_query_context
from app.query_engines.router import EngineRouter
from app.query_engines.shadow import RoutingEvidenceRepository
from app.query_engines.sqlbot.engine import SQLBotEngine
from app.query_engines.sqlbot.session_manager import SQLBotSessionManager
from app.scenarios.sales_ops.engine import SalesOpsDeterministicEngine
from app.scenarios.sales_ops.metrics import SALES_METRICS
from app.scenarios.sales_ops.runtime import resolve_sales_ops_context


def _format_value(metric_id: str, value: object) -> str:
    if value is None:
        return "数据不足"
    _, unit = SALES_METRICS[metric_id]
    if unit == "%":
        return f"{float(value) * 100:.2f}%"
    if unit.startswith("元"):
        return f"{float(value):,.2f} {unit}"
    if isinstance(value, int):
        return f"{value:,} {unit}"
    return f"{float(value):,.2f} {unit}"


def _compose_answer(result: QueryResult) -> str:
    values = result.rows[0] if result.rows else {}
    parts = [
        f"{SALES_METRICS[metric_id][0]}为"
        f"{_format_value(metric_id, value)}"
        for metric_id, value in values.items()
    ]
    period = result.evidence["time_range"]
    return (
        f"模拟数据：{period[0]} 至 {period[1]}（右开），"
        + "，".join(parts)
        + "。结果来自当前 ACTIVE sales_ops 数据集和语义版本。"
    )


class SalesOpsChatService:
    def __init__(
        self,
        db: Session,
        user: User,
        conversation_id: str,
    ):
        self.db = db
        self.user = user
        self.conversation_id = conversation_id

    def ask(self, question: str) -> dict:
        identity, platform_context = resolve_sales_ops_context(
            self.db,
            self.user,
        )
        query_context = build_query_context(
            self.db,
            conversation_id=self.conversation_id,
            platform_context=platform_context,
        )
        request = QueryRequest(
            question=question,
            identity_context=identity,
            scenario_id="sales_ops",
            conversation_state={
                "conversation_id": self.conversation_id,
            },
        )
        evidence_repository = RoutingEvidenceRepository(self.db)
        sqlbot = SQLBotEngine(
            session_manager=SQLBotSessionManager(
                on_bind=evidence_repository.record_session_binding
            )
        )
        routed = EngineRouter.from_settings(
            SalesOpsDeterministicEngine(self.db),
            sqlbot,
            evidence=evidence_repository,
        ).execute(
            request,
            query_context,
            deterministic_supported=True,
        )
        result = routed.result
        state_version = self._save_state(result)
        settings = get_settings()
        time_range = result.evidence["time_range"]
        query_plan = {
            "version": "sales-ops-1.0.0",
            "status": "ready",
            "intent": "metric_query",
            "metrics": list(result.columns),
            "dimensions": list(result.evidence.get("dimensions", [])),
            "filters": [],
            "time_range": {
                "start": time_range[0],
                "end_exclusive": time_range[1],
            },
            "comparison": None,
        }
        evidence = {
            **result.evidence,
            "data_time_range": {
                "start": time_range[0],
                "end_exclusive": time_range[1],
            },
            "analysis_run_id": result.run_id,
            "state_version": state_version,
            "answer_guard": {"status": "passed"},
            "sql": result.sql,
            "explanation_mode": "structured_result_composer",
        }
        return {
            "status": result.status,
            "answer": _compose_answer(result),
            "conversation_id": self.conversation_id,
            "state_version": state_version,
            "query_plan": query_plan,
            "result": {"metrics": result.rows[0] if result.rows else {}},
            "chart": result.chart_spec,
            "evidence": evidence,
            "query_result": result.as_dict(),
            "engine_routing": {
                "mode": settings.effective_query_engine_mode,
                "route_decision": routed.route_decision,
                "route_reason": routed.route_reason,
                "feature_flag_version": (
                    settings.query_engine_feature_flag_version
                ),
                "shadow_compared": routed.shadow_comparison is not None,
            },
        }

    def _save_state(self, result: QueryResult) -> int:
        now = datetime.now(UTC)
        state = self.db.get(SessionState, self.conversation_id)
        if state is None:
            state = SessionState(
                conversation_id=self.conversation_id,
                user_id=self.user.id,
                role_ids_json=json.dumps([self.user.role]),
                active_intent="metric_query",
                created_at=now,
                updated_at=now,
                expires_at=now + timedelta(days=7),
                state_version=1,
                status="active",
            )
            self.db.add(state)
        else:
            state.state_version += 1
            state.updated_at = now
            state.expires_at = now + timedelta(days=7)
            state.status = "active"
        state.active_metrics_json = json.dumps(list(result.columns))
        state.active_dimensions_json = json.dumps(
            result.evidence.get("dimensions", [])
        )
        state.active_filters_json = "[]"
        state.active_time_range_json = json.dumps({
            "start": result.evidence["time_range"][0],
            "end_exclusive": result.evidence["time_range"][1],
        })
        state.active_comparison_json = "null"
        state.active_entities_json = json.dumps({
            "scenario_id": "sales_ops",
        })
        state.current_step = "answered"
        run_ids = json.loads(state.source_run_ids_json or "[]")
        state.source_run_ids_json = json.dumps(
            (run_ids + [result.run_id])[-20:]
        )
        self.db.commit()
        return state.state_version
