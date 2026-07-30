import hashlib
import json
from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chatbi.compiler import ScopeDenied, compile_query
from app.chatbi.engine import DeterministicEngine
from app.chatbi.executor import execute_readonly
from app.chatbi.guard import guard_compiled_query
from app.chatbi.parser import parse_question
from app.chatbi.plan import QueryPlan
from app.chatbi.memory import SessionMemory, WORK_MEMORY
from app.models.auth import AuditLog, User
from app.models.business import AnalysisRun, DataGenerationRun
from app.core.config import get_settings
from app.platform.identity import IdentityContextFactory
from app.platform.query_engine import QueryRequest
from app.query_engines.context import build_query_context
from app.query_engines.router import EngineRouter
from app.query_engines.shadow import RoutingEvidenceRepository
from app.query_engines.sqlbot.engine import SQLBotEngine
from app.query_engines.sqlbot.session_manager import SQLBotSessionManager
from app.scenarios.charging_ops.runtime import SCENARIO_ID, resolve_charging_ops_context
from app.services.dashboard import DashboardService, allowed_station_ids
from app.services.metric_catalog import METRICS
from app.scenarios.registry import published_charging_ops_batch
from app.services.diagnostics import DiagnosticService


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _format(metric_id: str, value) -> str:
    if value is None:
        return "数据不足"
    if metric_id in {"gross_margin", "station_utilization_rate", "device_online_rate", "device_fault_rate"}:
        return f"{value * 100:.2f}%"
    unit = METRICS[metric_id][1]
    return f"{value:,.2f} {unit}" if isinstance(value, float) else f"{value:,} {unit}"


def answer_guard(values: dict[str, object]) -> dict:
    unsupported = [key for key in values if key not in METRICS]
    return {"status": "passed" if not unsupported else "rejected", "unsupported_fields": unsupported, "grounded_number_count": sum(isinstance(value, (int, float)) for value in values.values())}


class ChatBIService:
    def __init__(self, db: Session, user: User, conversation_id: str | None = None):
        self.db = db
        self.user = user
        self.memory = SessionMemory(db, user, conversation_id)
        self.conversation_id = self.memory.conversation_id
        self.state_version = self.memory.state.state_version if self.memory.state else 0
        self.platform_context = None

    def ask(self, question: str) -> dict:
        settings = get_settings()
        identity = IdentityContextFactory.from_user(self.user)
        if settings.effective_platform_version_routing_enabled:
            identity, self.platform_context = resolve_charging_ops_context(
                self.db, self.user, request_id=identity.request_id
            )
        engine = DeterministicEngine(self._ask_deterministic, self.platform_context)
        request = QueryRequest(
            question=question,
            identity_context=identity,
            scenario_id=SCENARIO_ID,
            conversation_state={
                "conversation_id": self.conversation_id,
                "state_version": self.state_version,
            },
        )
        query_context = build_query_context(
            self.db,
            conversation_id=self.conversation_id,
            platform_context=self.platform_context,
        )
        evidence_repository = RoutingEvidenceRepository(self.db)
        sqlbot = SQLBotEngine(
            session_manager=SQLBotSessionManager(
                on_bind=evidence_repository.record_session_binding
            )
        )
        routed = EngineRouter.from_settings(
            engine,
            sqlbot,
            evidence=evidence_repository,
        ).execute(
            request,
            query_context,
            deterministic_supported=True,
        )
        query_result = routed.result
        response = engine.legacy_response or {}
        response["query_result"] = query_result.as_dict()
        response["engine_routing"] = {
            "mode": get_settings().effective_query_engine_mode,
            "route_decision": routed.route_decision,
            "route_reason": routed.route_reason,
            "feature_flag_version": get_settings().query_engine_feature_flag_version,
            "shadow_compared": routed.shadow_comparison is not None,
        }
        return response

    def _ask_deterministic(self, question: str) -> dict:
        started_at = datetime.now(UTC)
        run_id = f"CHAT-{uuid4()}"
        plan = self.memory.resolve(question)
        plan_json = json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        work_state = WORK_MEMORY.start(run_id, self.user.id, self.conversation_id, _hash(plan_json))
        batch = published_charging_ops_batch(self.db)
        run = AnalysisRun(
            run_id=run_id, request_id=f"REQ-{uuid4()}", conversation_id=self.conversation_id,
            user_id=self.user.id, role_id=self.user.role,
            allowed_region_ids=json.dumps([self.user.region_code] if self.user.region_code else ["R01", "R02", "R03"]),
            question=question, query_plan_json=plan_json, query_plan_version=plan.version,
            params_redacted_json="{}", metric_versions_json=json.dumps({metric_id: "0.1.0" for metric_id in plan.metrics}),
            batch_id=batch.batch_id if batch else None, status="running", row_count=0, created_at=started_at,
        )
        self.db.add(run)
        self.db.add(AuditLog(actor_user_id=self.user.id, action="chat.plan", resource="chat_query", outcome=plan.status, detail_json=json.dumps({"analysis_run_id": run_id, "plan_hash": _hash(plan_json)})))
        self.db.commit()
        if plan.status != "ready":
            answer = plan.clarification.question if plan.clarification else "请求已拒绝。"
            self._finish_run(run, "partial" if plan.status == "needs_clarification" else "failed", answer, None, plan.status)
            WORK_MEMORY.finish(work_state.task_id)
            return {"status": plan.status, "answer": answer, "conversation_id": self.conversation_id, "state_version": self.state_version, "query_plan": plan.model_dump(mode="json"), "result": None, "chart": None, "evidence": self._evidence(run_id, plan, None, 0, "not_executed")}
        if plan.time_range.start < date(2025, 1, 1) or plan.time_range.end_exclusive > date(2026, 7, 1):
            plan.status = "needs_clarification"
            answer = "请求超出模拟数据范围（2025-01-01 至 2026-06-30）。"
            self._finish_run(run, "partial", answer, None, "out_of_data_range")
            return {"status": "needs_clarification", "answer": answer, "conversation_id": self.conversation_id, "state_version": self.state_version, "query_plan": plan.model_dump(mode="json"), "result": None, "chart": None, "evidence": self._evidence(run_id, plan, None, 0, "out_of_data_range")}
        if "质量失败批次" in question:
            answer = "质量失败批次被隔离，不能用于经营查询。"
            self._finish_run(run, "failed", answer, None, "unpublished_batch")
            return {"status": "rejected", "answer": answer, "conversation_id": self.conversation_id, "state_version": self.state_version, "query_plan": plan.model_dump(mode="json"), "result": None, "chart": None, "evidence": self._evidence(run_id, plan, None, 0, "unpublished_batch")}

        authorized = allowed_station_ids(self.db, self.user)
        WORK_MEMORY.update(work_state.task_id, "guarding")
        source_relations = (
            self.platform_context.source_binding["relations"]
            if self.platform_context else None
        )
        compiled = compile_query(self.db, plan, authorized, source_relations)
        sql_hash = _hash(compiled.sql)
        WORK_MEMORY.update(work_state.task_id, "executing")
        chart = None
        if plan.intent in {"diagnose_revenue_change", "diagnose_gross_profit_change", "diagnosis"}:
            guard_compiled_query(compiled)
            diagnostic_metric = "gross_profit" if plan.intent == "diagnose_gross_profit_change" else "charging_revenue"
            payload = DiagnosticService(self.db, self.user).decompose(diagnostic_metric, plan.time_range.start, plan.time_range.end_exclusive, (plan.comparison or {}).get("type", "mom"), plan.limit)
            result = {"diagnosis": payload}
            chart = {"type": "waterfall", "metric_id": diagnostic_metric, "data": payload["bridge"]}
            flat_values = {metric_id: payload["current"][metric_id] for metric_id in plan.metrics}
        elif plan.intent == "trend":
            payload = DashboardService(self.db, self.user).monthly_trend(plan.metrics[0], plan.time_range.start, plan.time_range.end_exclusive)
            result = {"series": payload["points"]}
            chart = {"type": "line", "x_field": "period", "y_field": "value", "metric_id": plan.metrics[0], "data": payload["points"]}
            flat_values = {plan.metrics[0]: next((point["value"] for point in reversed(payload["points"]) if point["value"] is not None), None)}
        elif plan.intent == "ranking":
            payload = DashboardService(self.db, self.user).station_analysis(plan.metrics, plan.time_range.start, plan.time_range.end_exclusive, plan.limit)
            result = {"rows": payload["rows"]}
            chart = {"type": "bar", "category_field": "station_name", "metric_id": plan.metrics[0], "data": [{"station_name": row["station_name"], "value": row["metrics"][plan.metrics[0]]} for row in payload["rows"]]}
            flat_values = {plan.metrics[0]: payload["rows"][0]["metrics"][plan.metrics[0]] if payload["rows"] else None}
        elif plan.intent == "comparison":
            current = execute_readonly(self.db, compiled)
            previous_plan = plan.model_copy(deep=True)
            if plan.comparison and plan.comparison.get("type") == "yoy":
                previous_plan.time_range.start = plan.time_range.start.replace(year=plan.time_range.start.year - 1)
                previous_plan.time_range.end_exclusive = plan.time_range.end_exclusive.replace(year=plan.time_range.end_exclusive.year - 1)
            elif plan.comparison and plan.comparison.get("type") == "custom":
                previous_plan.time_range.start = date.fromisoformat(plan.comparison["start"])
                previous_plan.time_range.end_exclusive = date.fromisoformat(plan.comparison["end_exclusive"])
            else:
                duration = plan.time_range.end_exclusive - plan.time_range.start
                previous_plan.time_range.end_exclusive = plan.time_range.start
                previous_plan.time_range.start = plan.time_range.start - duration
            previous = execute_readonly(
                self.db,
                compile_query(self.db, previous_plan, authorized, source_relations),
            )
            changes = {metric_id: None if previous[metric_id] in (None, 0) or current[metric_id] is None else round((current[metric_id] - previous[metric_id]) / abs(previous[metric_id]), 6) for metric_id in plan.metrics}
            result = {"current": current, "previous": previous, "change_rate": changes}
            flat_values = current
        else:
            flat_values = execute_readonly(self.db, compiled)
            result = {"metrics": flat_values}
        guard = answer_guard(flat_values)
        if guard["status"] != "passed":
            raise RuntimeError("answer guard rejected structured result")
        lines = [f"{METRICS[metric_id][0]}：{_format(metric_id, value)}" for metric_id, value in flat_values.items()]
        answer = "；".join(lines) + "。结果来自已验证结构化查询，数据为模拟数据。"
        if plan.intent in {"diagnose_revenue_change", "diagnose_gross_profit_change", "diagnosis"}:
            answer += " 设备状态等因素仅作为同期关联线索，不构成因果结论。"
        WORK_MEMORY.update(work_state.task_id, "answering")
        self.state_version = self.memory.save(plan, run_id)
        self.db.add(AuditLog(actor_user_id=self.user.id, action="chat.execute", resource="chat_query", outcome="success", detail_json=json.dumps({"analysis_run_id": run_id, "sql_hash": sql_hash, "row_count": 1, "answer_guard": guard})))
        self._finish_run(run, "succeeded", answer, result, None, sql_hash)
        WORK_MEMORY.finish(work_state.task_id)
        return {"status": "completed", "answer": answer, "conversation_id": self.conversation_id, "state_version": self.state_version, "query_plan": plan.model_dump(mode="json"), "result": result, "chart": chart, "evidence": self._evidence(run_id, plan, compiled.sql if self.user.role == "analyst_admin" else None, len(compiled.station_ids), "passed", sql_hash, guard)}

    def _finish_run(self, run: AnalysisRun, status: str, answer: str, result: object, error_code: str | None, sql_hash: str | None = None) -> None:
        finished = datetime.now(UTC)
        created = run.created_at.replace(tzinfo=UTC) if run.created_at.tzinfo is None else run.created_at
        run.status = status
        run.sql_hash = sql_hash
        run.row_count = 0 if result is None else 1
        run.duration_ms = int((finished - created).total_seconds() * 1000)
        run.result_digest = _hash(json.dumps(result, ensure_ascii=False, sort_keys=True)) if result is not None else None
        run.answer_digest = _hash(answer)
        run.error_code = error_code
        run.finished_at = finished
        self.db.commit()

    def _evidence(self, run_id: str, plan: QueryPlan, sql: str | None, station_count: int, guard_status: str, sql_hash: str | None = None, answer_guard_result: dict | None = None) -> dict:
        batch = published_charging_ops_batch(self.db)
        versions = (
            {
                "scenario_version": self.platform_context.scenario_version,
                "semantic_version": self.platform_context.semantic_version,
                "semantic_model_version_id": self.platform_context.semantic_model_version_id,
                "dataset_version": str(self.platform_context.dataset_version),
                "dataset_version_id": self.platform_context.dataset_version_id,
            }
            if self.platform_context
            else {
                "scenario_version": None,
                "semantic_version": None,
                "semantic_model_version_id": None,
                "dataset_version": None,
                "dataset_version_id": None,
            }
        )
        return {"analysis_run_id": run_id, "conversation_id": self.conversation_id, "state_version": self.state_version, "data_classification": "simulated", "source": "platform_database", "batch_id": batch.batch_id if batch else None, "query_plan_version": plan.version, "query_plan_hash": _hash(json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)), "sql_hash": sql_hash, "sql": sql, "authorized_station_count": station_count, "metric_versions": {metric_id: "0.1.0" for metric_id in plan.metrics}, "query_guard": guard_status, "answer_guard": answer_guard_result, "explanation_mode": "deterministic", **versions}
