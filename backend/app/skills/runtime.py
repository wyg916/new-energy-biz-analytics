from __future__ import annotations

import json
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from sqlalchemy.orm import Session

from app.memory.episodic import EpisodicMemoryService, EpisodicRun
from app.memory.models import SkillExecutionRecord
from app.memory.procedural import SkillRegistry
from app.models.auth import User
from app.platform.identity import IdentityContextFactory
from app.skills.adapters import AnalysisAdapter, AnalysisAdapterRegistry, previous_period
from app.skills.contracts import SkillOutput, SkillRequest


class SkillExecutionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class SkillExecutor:
    def __init__(
        self,
        db: Session,
        user: User,
        *,
        adapter_registry: AnalysisAdapterRegistry | None = None,
    ) -> None:
        self.db = db
        self.user = user
        self.identity = IdentityContextFactory.from_user(user)
        self.adapters = adapter_registry or AnalysisAdapterRegistry(db, user)
        self._handlers = {
            "revenue_decline_diagnosis": self._revenue,
            "order_anomaly_analysis": self._orders,
            "gross_profit_change_decomposition": self._gross_profit,
            "station_efficiency_diagnosis": self._efficiency,
            "operating_report_generation": self._report,
        }

    def execute(self, request: SkillRequest) -> SkillOutput:
        if not request.start < request.end_exclusive:
            raise SkillExecutionError("INVALID_TIME_RANGE", "Skill 时间范围不合法")
        skill = SkillRegistry(self.db, self.identity).match(
            skill_code=request.skill_code,
            scenario_id=request.scenario_id,
        )
        if skill is None:
            raise SkillExecutionError("SKILL_NOT_ACTIVE", "当前场景没有可执行的 ACTIVE Skill")
        handler = self._handlers.get(request.skill_code)
        if handler is None:
            raise SkillExecutionError("SKILL_HANDLER_MISSING", "Skill 执行器未注册")
        adapter = self.adapters.get(request.scenario_id)
        run_id = request.run_id or f"SKRUN-{uuid4()}"
        trace_id = request.trace_id or f"TRACE-{uuid4()}"
        task_id = f"TASK-{uuid4()}"
        execution = SkillExecutionRecord(
            execution_id=f"SKEXEC-{uuid4()}",
            skill_id=skill.skill_id,
            tenant_id=self.identity.tenant_id,
            workspace_id=self.identity.workspace_id,
            user_id=self.identity.subject_id,
            scenario_id=request.scenario_id,
            session_id=request.session_id,
            run_id=run_id,
            trace_id=trace_id,
            task_id=task_id,
            status="RUNNING",
            input_json=request.model_dump_json(),
        )
        self.db.add(execution)
        self.db.commit()
        started = perf_counter()
        steps: list[dict] = []
        try:
            output = handler(adapter, request, run_id, trace_id, task_id, steps)
            execution.status = "COMPLETED"
            execution.output_json = output.model_dump_json()
            execution.steps_json = json.dumps(steps, ensure_ascii=False)
            execution.duration_ms = int((perf_counter() - started) * 1000)
            execution.finished_at = datetime.now(UTC)
            self.db.commit()
            self._write_episode(output, request, adapter, execution)
            return output
        except Exception as exc:
            execution.status = "FAILED"
            execution.steps_json = json.dumps(steps, ensure_ascii=False)
            execution.error_code = getattr(exc, "code", type(exc).__name__)
            execution.error_message = str(exc)[:1000]
            execution.duration_ms = int((perf_counter() - started) * 1000)
            execution.finished_at = datetime.now(UTC)
            self.db.commit()
            raise

    def _analyze(
        self,
        adapter: AnalysisAdapter,
        request: SkillRequest,
        *,
        metric_id: str,
        run_id: str,
        trace_id: str,
        task_id: str,
        steps: list[dict],
        include_drivers: bool,
    ) -> SkillOutput:
        dimension = request.dimension or adapter.default_dimension
        previous_start, previous_end = previous_period(
            request.start, request.end_exclusive, request.comparison
        )
        self._step(steps, "parse_target", "metric_registry", run_id)
        metadata = adapter.metric_metadata(metric_id)
        self._step(steps, "resolve_periods", "procedure_parameter", run_id)
        self._step(steps, "query_current", "deterministic_engine", run_id)
        current = adapter.metrics(request.start, request.end_exclusive, (metric_id,))[metric_id]
        self._step(steps, "query_comparison", "deterministic_engine", run_id)
        previous = adapter.metrics(previous_start, previous_end, (metric_id,))[metric_id]
        delta = None if current is None or previous is None else round(float(current) - float(previous), 6)
        change_rate = None if delta is None or previous in (None, 0) else round(delta / abs(float(previous)), 6)
        self._step(steps, "dimension_contribution", "analysis_adapter", run_id)
        current_rows = adapter.breakdown(
            request.start, request.end_exclusive, metric_id, dimension, request.limit
        )
        previous_rows = adapter.breakdown(
            previous_start, previous_end, metric_id, dimension, request.limit
        )
        previous_map = {row["dimension"]: row for row in previous_rows}
        contributions = []
        for row in current_rows:
            prior = previous_map.get(row["dimension"], {"value": 0})
            value = row["value"]
            prior_value = prior["value"]
            contribution = None if value is None or prior_value is None else round(float(value) - float(prior_value), 6)
            contributions.append({
                "dimension": dimension,
                "member": row["dimension"],
                "member_name": row["dimension_name"],
                "current": value,
                "previous": prior_value,
                "contribution": contribution,
                "classification": "verified_calculation",
            })
        contributions.sort(
            key=lambda item: abs(item["contribution"] or 0), reverse=True
        )
        drivers = adapter.drivers(
            request.skill_code, request.start, request.end_exclusive, request.comparison
        ) if include_drivers else ()
        self._step(steps, "detect_anomaly", "deterministic_rule", run_id)
        triggered = change_rate is not None and abs(change_rate) >= 0.15
        anomalies = [{
            "metric_id": metric_id,
            "rule": "absolute_change_rate_gte_15pct",
            "triggered": triggered,
            "change_rate": change_rate,
            "severity": (
                "high" if triggered and abs(change_rate) >= 0.30
                else "medium" if triggered else "none"
            ),
            "classification": "verified_rule_result",
        }]
        negative = [item for item in contributions if (item["contribution"] or 0) < 0]
        candidate_causes = [{
            "statement": f"{item['member_name']}为主要负向贡献项，可能与该维度经营变化相关。",
            "classification": "candidate_cause",
            "evidence_ref": f"contribution:{index}",
        } for index, item in enumerate(negative[:3])]
        recommended = [{
            "action": f"复核{item['member_name']}的订单、价格、成本和运营事件明细。",
            "classification": "recommendation",
            "evidence_ref": f"contribution:{index}",
        } for index, item in enumerate(negative[:3])]
        self._step(steps, "retrieve_definition", "metric_registry", run_id)
        reconciliation = {
            "target_change": delta,
            "dimension_contribution_sum": round(
                sum(item["contribution"] or 0 for item in contributions), 6
            ),
            "driver_contribution_sum": (
                round(sum(item["contribution"] or 0 for item in drivers), 6)
                if drivers else None
            ),
        }
        self._step(steps, "validate_reconciliation", "deterministic_rule", run_id)
        conclusion = (
            f"模拟数据中，{metadata['metric_name']}本期为 {current}，"
            f"对比期为 {previous}，变化 {delta}（变化率 {change_rate}）。"
        )
        self._step(steps, "compose_recommendation", "evidence_template", run_id)
        return SkillOutput(
            conclusion=conclusion,
            metric_change={
                "metric_id": metric_id,
                "current": current,
                "previous": previous,
                "delta": delta,
                "change_rate": change_rate,
                "classification": "verified_fact",
            },
            time_comparison={
                "current": [request.start.isoformat(), request.end_exclusive.isoformat()],
                "previous": [previous_start.isoformat(), previous_end.isoformat()],
                "comparison": request.comparison,
            },
            contribution_breakdown=[*drivers, *contributions],
            anomalies=anomalies,
            evidence=[metadata, {"reconciliation": reconciliation}],
            candidate_causes=candidate_causes,
            recommended_actions=recommended,
            limitations=[
                "结果来自固定种子模拟数据，不代表真实企业经营结果。",
                "统计关联和候选根因不构成因果结论。",
                "行动建议需结合业务负责人复核后执行。",
            ],
            confidence=0.9 if delta is not None else 0.5,
            run_id=run_id,
            trace_id=trace_id,
            task_id=task_id,
            skill_code=request.skill_code,
            scenario_id=request.scenario_id,
            steps=steps,
        )

    def _revenue(self, adapter, request, run_id, trace_id, task_id, steps):
        return self._analyze(
            adapter,
            request,
            metric_id=request.metric_id or adapter.revenue_metric,
            run_id=run_id,
            trace_id=trace_id,
            task_id=task_id,
            steps=steps,
            include_drivers=True,
        )

    def _orders(self, adapter, request, run_id, trace_id, task_id, steps):
        return self._analyze(
            adapter,
            request,
            metric_id=request.metric_id or adapter.order_metric,
            run_id=run_id,
            trace_id=trace_id,
            task_id=task_id,
            steps=steps,
            include_drivers=False,
        )

    def _gross_profit(self, adapter, request, run_id, trace_id, task_id, steps):
        return self._analyze(
            adapter,
            request,
            metric_id=request.metric_id or adapter.gross_profit_metric,
            run_id=run_id,
            trace_id=trace_id,
            task_id=task_id,
            steps=steps,
            include_drivers=True,
        )

    def _efficiency(self, adapter, request, run_id, trace_id, task_id, steps):
        if adapter.efficiency_metric is None:
            raise SkillExecutionError(
                "SKILL_SCENARIO_UNSUPPORTED",
                "当前场景未发布场站效率指标",
            )
        return self._analyze(
            adapter,
            request,
            metric_id=request.metric_id or adapter.efficiency_metric,
            run_id=run_id,
            trace_id=trace_id,
            task_id=task_id,
            steps=steps,
            include_drivers=False,
        )

    def _report(self, adapter, request, run_id, trace_id, task_id, steps):
        previous_start, previous_end = previous_period(
            request.start, request.end_exclusive, request.comparison
        )
        metric_ids = adapter.report_metrics()
        self._step(steps, "parse_target", "metric_registry", run_id)
        self._step(steps, "resolve_periods", "procedure_parameter", run_id)
        self._step(steps, "query_current", "deterministic_engine", run_id)
        current = adapter.metrics(request.start, request.end_exclusive, metric_ids)
        self._step(steps, "query_comparison", "deterministic_engine", run_id)
        previous = adapter.metrics(previous_start, previous_end, metric_ids)
        changes = {
            metric: None if current[metric] is None or previous[metric] is None
            else round(float(current[metric]) - float(previous[metric]), 6)
            for metric in metric_ids
        }
        self._step(steps, "dimension_contribution", "analysis_adapter", run_id)
        primary = adapter.revenue_metric
        contributions = self._analyze(
            adapter,
            request,
            metric_id=primary,
            run_id=run_id,
            trace_id=trace_id,
            task_id=task_id,
            steps=steps,
            include_drivers=False,
        )
        self._step(steps, "write_report_draft", "evidence_template", run_id)
        return SkillOutput(
            conclusion="模拟数据经营报告草稿已生成；所有数字均来自当前已发布语义层的确定性结果。",
            metric_change={
                "metrics": current,
                "previous": previous,
                "changes": changes,
                "classification": "verified_fact",
            },
            time_comparison=contributions.time_comparison,
            contribution_breakdown=contributions.contribution_breakdown,
            anomalies=contributions.anomalies,
            evidence=[
                *[adapter.metric_metadata(metric) for metric in metric_ids],
                {"report_type": "auditable_draft", "automatic_delivery": False},
            ],
            candidate_causes=contributions.candidate_causes,
            recommended_actions=contributions.recommended_actions,
            limitations=[
                "本报告仅为可审核草稿，不会自动发送或触发工单。",
                "结果来自固定种子模拟数据，不代表真实企业经营结果。",
                "统计关联和候选根因不构成因果结论。",
            ],
            confidence=contributions.confidence,
            run_id=run_id,
            trace_id=trace_id,
            task_id=task_id,
            skill_code=request.skill_code,
            scenario_id=request.scenario_id,
            steps=steps,
        )

    @staticmethod
    def _step(steps: list[dict], code: str, tool: str, run_id: str) -> None:
        steps.append({
            "step_id": f"STEP-{uuid4()}",
            "code": code,
            "tool": tool,
            "status": "COMPLETED",
            "run_id": run_id,
        })

    def _write_episode(
        self,
        output: SkillOutput,
        request: SkillRequest,
        adapter: AnalysisAdapter,
        execution: SkillExecutionRecord,
    ) -> None:
        output.steps.append({
            "step_id": f"STEP-{uuid4()}",
            "code": "write_episode",
            "tool": "episodic_memory",
            "status": "COMPLETED",
            "run_id": output.run_id,
        })
        EpisodicMemoryService(self.db, self.identity).record_success(EpisodicRun(
            run_id=output.run_id,
            trace_id=output.trace_id,
            session_id=request.session_id or f"SKILL-{output.task_id}",
            raw_question=f"执行 Skill {request.skill_code}",
            normalized_question=f"{request.scenario_id}:{request.skill_code}",
            scenario_id=request.scenario_id,
            dataset_version="ACTIVE",
            semantic_version="ACTIVE",
            engine="deterministic_skill",
            query_plan={
                "skill_code": request.skill_code,
                "start": request.start.isoformat(),
                "end_exclusive": request.end_exclusive.isoformat(),
                "comparison": request.comparison,
            },
            actual_sql=None,
            result_summary={
                "metric_change": output.metric_change,
                "top_contributions": output.contribution_breakdown[:5],
                "anomalies": output.anomalies,
            },
            rag_evidence=output.evidence,
            final_answer=output.conclusion,
            skill_code=request.skill_code,
            steps=output.steps,
            errors=[],
            adopted=None,
            runtime_cost={"token_usage": 0},
            latency_ms=execution.duration_ms or 0,
        ))
