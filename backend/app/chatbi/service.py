import hashlib
import json
from datetime import date
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chatbi.compiler import ScopeDenied, compile_query
from app.chatbi.executor import execute_readonly
from app.chatbi.parser import parse_question
from app.chatbi.plan import QueryPlan
from app.models.auth import AuditLog, User
from app.models.business import DataGenerationRun
from app.services.dashboard import DashboardService, allowed_station_ids
from app.services.metric_catalog import METRICS


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
    def __init__(self, db: Session, user: User):
        self.db = db
        self.user = user

    def ask(self, question: str) -> dict:
        run_id = f"CHAT-{uuid4()}"
        plan = parse_question(question)
        plan_json = json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        self.db.add(AuditLog(actor_user_id=self.user.id, action="chat.plan", resource="chat_query", outcome=plan.status, detail_json=json.dumps({"analysis_run_id": run_id, "plan_hash": _hash(plan_json)})))
        self.db.commit()
        if plan.status != "ready":
            return {"status": plan.status, "answer": plan.clarification.question if plan.clarification else "请求已拒绝。", "query_plan": plan.model_dump(mode="json"), "result": None, "chart": None, "evidence": self._evidence(run_id, plan, None, 0, "not_executed")}
        if plan.time_range.start < date(2025, 1, 1) or plan.time_range.end_exclusive > date(2026, 7, 1):
            plan.status = "needs_clarification"
            return {"status": "needs_clarification", "answer": "请求超出模拟数据范围（2025-01-01 至 2026-06-30）。", "query_plan": plan.model_dump(mode="json"), "result": None, "chart": None, "evidence": self._evidence(run_id, plan, None, 0, "out_of_data_range")}
        if "质量失败批次" in question:
            return {"status": "rejected", "answer": "质量失败批次被隔离，不能用于经营查询。", "query_plan": plan.model_dump(mode="json"), "result": None, "chart": None, "evidence": self._evidence(run_id, plan, None, 0, "unpublished_batch")}

        authorized = allowed_station_ids(self.db, self.user)
        compiled = compile_query(self.db, plan, authorized)
        sql_hash = _hash(compiled.sql)
        chart = None
        if plan.intent == "trend":
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
            previous = execute_readonly(self.db, compile_query(self.db, previous_plan, authorized))
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
        self.db.add(AuditLog(actor_user_id=self.user.id, action="chat.execute", resource="chat_query", outcome="success", detail_json=json.dumps({"analysis_run_id": run_id, "sql_hash": sql_hash, "row_count": 1, "answer_guard": guard})))
        self.db.commit()
        return {"status": "completed", "answer": answer, "query_plan": plan.model_dump(mode="json"), "result": result, "chart": chart, "evidence": self._evidence(run_id, plan, compiled.sql if self.user.role == "analyst_admin" else None, len(compiled.station_ids), "passed", sql_hash, guard)}

    def _evidence(self, run_id: str, plan: QueryPlan, sql: str | None, station_count: int, guard_status: str, sql_hash: str | None = None, answer_guard_result: dict | None = None) -> dict:
        batch = self.db.scalar(select(DataGenerationRun).where(DataGenerationRun.quality_status == "passed").order_by(DataGenerationRun.finished_at.desc()))
        return {"analysis_run_id": run_id, "data_classification": "simulated", "source": "platform_database", "batch_id": batch.batch_id if batch else None, "query_plan_version": plan.version, "query_plan_hash": _hash(json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)), "sql_hash": sql_hash, "sql": sql, "authorized_station_count": station_count, "metric_versions": {metric_id: "0.1.0" for metric_id in plan.metrics}, "query_guard": guard_status, "answer_guard": answer_guard_result, "explanation_mode": "deterministic"}
