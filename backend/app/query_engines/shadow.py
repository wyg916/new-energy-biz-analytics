import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.models.query_routing import (
    QueryRouteDecisionRecord,
    ShadowEvaluation,
    SQLBotSessionBindingRecord,
)
from app.platform.query_engine import QueryContext, QueryRequest, QueryResult
from app.query_engines.sqlbot.contracts import SQLBotSession
from app.governance.audit import record_governance_event


def normalized_question(question: str) -> str:
    return re.sub(r"\s+", " ", question.strip().lower())


def result_hash(result: QueryResult | None) -> str | None:
    if result is None:
        return None
    payload = {
        "columns": result.columns,
        "rows": result.rows,
        "scenario": result.scenario,
        "scenario_version": result.scenario_version,
        "semantic_version": result.semantic_version,
        "dataset_version": result.dataset_version,
        "status": result.status,
    }
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def _evidence_match(
    deterministic: QueryResult,
    sqlbot: QueryResult,
    key: str,
) -> int | None:
    left = deterministic.evidence.get(key)
    right = sqlbot.evidence.get(key)
    if left is None or right is None:
        return None
    return int(left == right)


@dataclass(frozen=True)
class ShadowComparison:
    deterministic_result_hash: str | None
    sqlbot_result_hash: str | None
    execution_accuracy: float
    metric_value_match: int
    time_range_match: int | None
    dimension_match: int | None
    permission_result: str

    @property
    def major_conflict(self) -> bool:
        return (
            self.execution_accuracy < 1.0
            or self.metric_value_match != 1
            or self.time_range_match == 0
            or self.dimension_match == 0
            or self.permission_result != "PASS"
        )


def compare_results(
    deterministic: QueryResult,
    sqlbot: QueryResult,
) -> ShadowComparison:
    left_hash = result_hash(deterministic)
    right_hash = result_hash(sqlbot)
    exact = int(left_hash == right_hash)
    metric_match = _evidence_match(
        deterministic,
        sqlbot,
        "metric_values",
    )
    if metric_match is None:
        metric_match = exact
    permission_result = (
        "PASS"
        if sqlbot.evidence.get("query_guard") == "passed"
        and deterministic.status in {"completed", "succeeded"}
        and sqlbot.status == "completed"
        else "FAIL"
    )
    return ShadowComparison(
        deterministic_result_hash=left_hash,
        sqlbot_result_hash=right_hash,
        execution_accuracy=float(exact),
        metric_value_match=metric_match,
        time_range_match=_evidence_match(
            deterministic,
            sqlbot,
            "time_range",
        ),
        dimension_match=_evidence_match(
            deterministic,
            sqlbot,
            "dimensions",
        ),
        permission_result=permission_result,
    )


class RoutingEvidenceRepository:
    def __init__(self, db: Session):
        self.db = db

    def record_session_binding(self, session: SQLBotSession) -> None:
        raw = json.dumps(session.key.as_tuple(), ensure_ascii=False)
        binding_hash = hashlib.sha256(raw.encode()).hexdigest()
        record = self.db.scalar(
            select(SQLBotSessionBindingRecord).where(
                SQLBotSessionBindingRecord.binding_hash == binding_hash
            )
        )
        if record is None:
            record = SQLBotSessionBindingRecord(
                binding_id=f"SB-{uuid4()}",
                binding_hash=binding_hash,
                tenant_id=session.key.tenant_id,
                workspace_id=session.key.workspace_id,
                subject_id=session.key.subject_id,
                conversation_id=session.key.conversation_id,
                scenario_id=session.key.scenario_id,
                scenario_version=session.key.scenario_version,
                semantic_version=session.key.semantic_version,
                dataset_version=session.key.dataset_version,
                external_chat_id=session.external_chat_id,
                generation=session.generation,
                status="ACTIVE",
                created_at=session.created_at,
                last_used_at=session.last_used_at,
            )
            self.db.add(record)
        else:
            record.external_chat_id = session.external_chat_id
            record.generation = session.generation
            record.status = "ACTIVE"
            record.last_used_at = session.last_used_at
            record.invalidated_at = None
        self.db.commit()

    def record_route(
        self,
        request: QueryRequest,
        context: QueryContext,
        *,
        route_decision: str,
        route_reason: str,
        mode: str,
        engine: str,
        feature_flag_version: str,
        run_id: str | None,
    ) -> QueryRouteDecisionRecord:
        record = QueryRouteDecisionRecord(
            route_decision_id=f"RD-{uuid4()}",
            tenant_id=request.identity_context.tenant_id,
            workspace_id=request.identity_context.workspace_id,
            subject_id=request.identity_context.subject_id,
            route_decision=route_decision,
            route_reason=route_reason,
            mode=mode,
            engine=engine,
            scenario=request.scenario_id,
            scenario_version=context.scenario_version,
            semantic_version=context.semantic_version,
            dataset_version=context.dataset_version,
            feature_flag_version=feature_flag_version,
            run_id=run_id,
            trace_id=request.identity_context.request_id,
        )
        self.db.add(record)
        self.db.commit()
        return record

    def record_shadow(
        self,
        request: QueryRequest,
        context: QueryContext,
        deterministic: QueryResult,
        sqlbot: QueryResult | None,
        *,
        route_mode: str,
        error_code: str | None = None,
        error: str | None = None,
    ) -> ShadowEvaluation:
        comparison = (
            compare_results(deterministic, sqlbot)
            if sqlbot is not None
            else None
        )
        token_usage = (
            sqlbot.evidence.get("token_usage")
            if sqlbot is not None
            else None
        )
        record = ShadowEvaluation(
            shadow_evaluation_id=f"SE-{uuid4()}",
            tenant_id=request.identity_context.tenant_id,
            workspace_id=request.identity_context.workspace_id,
            subject_id=request.identity_context.subject_id,
            conversation_id=context.conversation_id,
            question=request.question,
            normalized_question=normalized_question(request.question),
            route_mode=route_mode,
            scenario=request.scenario_id,
            scenario_version=context.scenario_version,
            semantic_version=context.semantic_version,
            dataset_version=context.dataset_version,
            deterministic_sql=deterministic.sql,
            sqlbot_sql=sqlbot.sql if sqlbot else None,
            deterministic_result_hash=(
                comparison.deterministic_result_hash
                if comparison
                else result_hash(deterministic)
            ),
            sqlbot_result_hash=(
                comparison.sqlbot_result_hash if comparison else None
            ),
            execution_accuracy=(
                comparison.execution_accuracy if comparison else None
            ),
            metric_value_match=(
                comparison.metric_value_match if comparison else None
            ),
            time_range_match=(
                comparison.time_range_match if comparison else None
            ),
            dimension_match=(
                comparison.dimension_match if comparison else None
            ),
            permission_result=(
                comparison.permission_result if comparison else "NOT_EXECUTED"
            ),
            row_count=len(sqlbot.rows) if sqlbot else 0,
            latency_ms=sqlbot.execution_time if sqlbot else None,
            token_usage=token_usage if isinstance(token_usage, int) else None,
            error_code=error_code,
            error=error,
            run_id=deterministic.run_id,
            trace_id=request.identity_context.request_id,
        )
        self.db.add(record)
        if inspect(self.db.get_bind()).has_table("governance_audit_event"):
            record_governance_event(
                self.db,
                request.identity_context,
                action="sqlbot.shadow",
                resource_type="sqlbot_shadow",
                resource_id=record.shadow_evaluation_id,
                result="SUCCESS" if sqlbot is not None else "FAILED",
                trace_id=request.identity_context.request_id,
                detail={
                    "scenario_id": request.scenario_id,
                    "permission_result": record.permission_result,
                    "error_code": error_code,
                    "long_term_fact_written": False,
                },
            )
        self.db.commit()
        return record
