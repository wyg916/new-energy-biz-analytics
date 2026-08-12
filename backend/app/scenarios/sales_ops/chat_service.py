import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from time import perf_counter

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
from app.query_engines.sqlbot.client import runtime_sqlbot_client
from app.query_engines.sqlbot.readonly_executor import execute_generated_readonly
from app.query_engines.sqlbot.session_manager import runtime_session_manager
from app.query_engines.sqlbot.understanding import understand_query
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
    data_label = (
        "公开数据样本"
        if str(result.evidence.get("data_classification", "")).upper().startswith("OPEN_SOURCE")
        else "模拟数据"
    )
    if result.engine == "sqlbot":
        period = result.evidence.get("time_range")
        period_text = (
            f"{period[0]} 至 {period[1]}（右开）"
            if period and all(period)
            else "当前已发布数据范围"
        )
        return (
            f"{data_label}：{period_text}，受控查询返回 {len(result.rows)} 行、"
            f"{len(result.columns)} 列。所有数字均来自通过 Query Guard、"
            "只读执行与 Answer Guard 的结构化结果。"
        )
    values = result.rows[0] if result.rows else {}
    parts = [
        f"{SALES_METRICS[metric_id][0]}为"
        f"{_format_value(metric_id, value)}"
        for metric_id, value in values.items()
    ]
    period = result.evidence["time_range"]
    return (
        f"{data_label}：{period[0]} 至 {period[1]}（右开），"
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
        service_started = perf_counter()
        phase_started = perf_counter()
        identity, platform_context = resolve_sales_ops_context(
            self.db,
            self.user,
        )
        service_timings = {
            "resolve_context_ms": int((perf_counter() - phase_started) * 1000),
        }
        phase_started = perf_counter()
        query_context = build_query_context(
            self.db,
            conversation_id=self.conversation_id,
            platform_context=platform_context,
        )
        service_timings["build_query_context_ms"] = int(
            (perf_counter() - phase_started) * 1000
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
        phase_started = perf_counter()
        sqlbot = SQLBotEngine(
            client=runtime_sqlbot_client(),
            session_manager=runtime_session_manager(),
            session_on_bind=evidence_repository.record_session_binding,
            generated_sql_executor=execute_generated_readonly,
        )
        service_timings["engine_setup_ms"] = int(
            (perf_counter() - phase_started) * 1000
        )
        phase_started = perf_counter()
        understanding = understand_query(request, query_context)
        service_timings["understanding_ms"] = int(
            (perf_counter() - phase_started) * 1000
        )
        phase_started = perf_counter()
        routed = EngineRouter.from_settings(
            SalesOpsDeterministicEngine(self.db),
            sqlbot,
            evidence=evidence_repository,
        ).execute(
            request,
            query_context,
            deterministic_supported=understanding.deterministic_preferred,
        )
        service_timings["route_and_query_ms"] = int(
            (perf_counter() - phase_started) * 1000
        )
        result = routed.result
        settings = get_settings()
        legacy_disabled_shadow = (
            settings.effective_query_engine_mode == "SHADOW"
            and not settings.sqlbot_engine_enabled
            and routed.route_decision == "DETERMINISTIC_ONLY"
        )
        if legacy_disabled_shadow and "SQLBOT_DISABLED" not in result.warnings:
            result = replace(
                result,
                warnings=(*result.warnings, "SQLBOT_DISABLED"),
            )
        phase_started = perf_counter()
        state_version = self._save_state(result)
        service_timings["save_state_ms"] = int(
            (perf_counter() - phase_started) * 1000
        )
        service_timings["service_total_ms"] = int(
            (perf_counter() - service_started) * 1000
        )
        time_range = result.evidence.get("time_range")
        dimensions = list(result.evidence.get("dimensions", []))
        metrics = list(result.evidence.get("metrics", [])) or [
            column for column in result.columns if column not in dimensions
        ]
        query_plan = {
            "version": "sales-ops-1.0.0",
            "status": "ready",
            "intent": "metric_query",
            "metrics": metrics,
            "dimensions": dimensions,
            "filters": [],
            "time_range": (
                {
                    "start": time_range[0],
                    "end_exclusive": time_range[1],
                }
                if time_range and all(time_range)
                else None
            ),
            "comparison": None,
        }
        evidence = {
            **result.evidence,
            "data_time_range": (
                {
                    "start": time_range[0],
                    "end_exclusive": time_range[1],
                }
                if time_range and all(time_range)
                else None
            ),
            "analysis_run_id": result.run_id,
            "state_version": state_version,
            "answer_guard": {"status": "passed"},
            "sql": result.sql,
            "explanation_mode": "structured_result_composer",
            "service_latency_profile": service_timings,
        }
        return {
            "status": result.status,
            "answer": _compose_answer(result),
            "conversation_id": self.conversation_id,
            "state_version": state_version,
            "query_plan": query_plan,
            "result": (
                {"rows": list(result.rows)}
                if result.engine == "sqlbot"
                else {"metrics": result.rows[0] if result.rows else {}}
            ),
            "chart": result.chart_spec,
            "evidence": evidence,
            "query_result": result.as_dict(),
            "engine_routing": (
                {
                    "mode": "SHADOW",
                    "route_decision": "DETERMINISTIC_WITH_SHADOW",
                    "route_reason": "SQLBOT_DISABLED",
                    "feature_flag_version": (
                        settings.query_engine_feature_flag_version
                    ),
                    "shadow_compared": False,
                }
                if legacy_disabled_shadow
                else {
                    "mode": settings.effective_query_engine_mode,
                    "feature_flag_version": (
                        settings.query_engine_feature_flag_version
                    ),
                    "shadow_compared": routed.shadow_comparison is not None,
                    **routed.routing_evidence(),
                }
            ),
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
        time_range = result.evidence.get("time_range")
        state.active_time_range_json = json.dumps(
            {
                "start": time_range[0],
                "end_exclusive": time_range[1],
            }
            if time_range and all(time_range)
            else None
        )
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
