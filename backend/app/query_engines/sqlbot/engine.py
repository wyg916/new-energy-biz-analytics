import hashlib
import json
import re
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from time import perf_counter
from typing import Callable
from uuid import uuid4

from app.chatbi.guard import QueryRejected, guard_sqlbot_sql
from app.core.config import get_settings
from app.platform.query_engine import QueryContext, QueryEngine, QueryRequest, QueryResult
from app.query_engines.sqlbot.client import SQLBotClient
from app.query_engines.sqlbot.contracts import SQLBotSession, SQLBotSessionKey
from app.query_engines.sqlbot.error_mapper import (
    SQLBotEngineError,
    SQLBotErrorCode,
)
from app.query_engines.sqlbot.feature_flags import SQLBotFeatureFlags
from app.query_engines.sqlbot.health import CircuitBreaker
from app.query_engines.sqlbot.limit_policy import apply_limit_policy
from app.query_engines.sqlbot.policy import SQLPolicyDecision, validate_generated_sql
from app.query_engines.sqlbot.prompt_context import (
    authorized_examples,
    build_guard_repair_question,
    exact_authorized_example,
)
from app.query_engines.sqlbot.request_mapper import map_question_request
from app.query_engines.sqlbot.response_parser import parse_response
from app.query_engines.sqlbot.result_guard import validate_result
from app.query_engines.sqlbot.schema_catalog import retrieve_schema
from app.query_engines.sqlbot.session_manager import SQLBotSessionManager
from app.query_engines.sqlbot.understanding import understand_query


GeneratedSQLExecutor = Callable[
    [str, QueryRequest, QueryContext],
    tuple[tuple[str, ...], tuple[dict, ...]],
]
SQLPolicyGuard = Callable[[str, QueryContext], None]


def _extract_sql_time_range(sql: str) -> list[str] | None:
    """Return the bounded ISO date range already present in guarded SQL."""
    values = sorted(set(re.findall(r"20\d{2}-\d{2}-\d{2}", sql)))
    return [values[0], values[-1]] if len(values) >= 2 else None


def _normalize_result_contract(
    columns: tuple[str, ...],
    rows: tuple[dict, ...],
    matched_metrics: tuple[str, ...],
    matched_dimensions: tuple[str, ...] = (),
) -> tuple[tuple[str, ...], tuple[dict, ...], dict[str, object]]:
    """Expose stable semantic keys and grains after guarded SQL execution."""
    if not rows:
        profile: dict[str, object] = {"status": "not_applicable"}
        return columns, rows, profile
    removed_columns = tuple(
        column
        for column in columns
        if column.endswith("_id")
        and column[:-3] in matched_dimensions
        and f"{column[:-3]}_name" in columns
    )
    working_columns = tuple(column for column in columns if column not in removed_columns)
    working_rows = tuple(
        {key: value for key, value in row.items() if key not in removed_columns}
        for row in rows
    )
    normalized_time_columns: list[str] = []
    temporal_rows: list[dict] = []
    for row in working_rows:
        normalized_row = dict(row)
        for column, value in row.items():
            if column.lower() != "month" or value is None:
                continue
            normalized = value
            if isinstance(value, (date, datetime)):
                normalized = value.strftime("%Y-%m")
            elif isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}.*", value):
                normalized = value[:7]
            if normalized != value:
                normalized_row[column] = normalized
                normalized_time_columns.append(column)
        temporal_rows.append(normalized_row)
    working_rows = tuple(temporal_rows)
    metric_profile: dict[str, object] = {"status": "not_applicable"}
    if len(matched_metrics) != 1:
        return working_columns, working_rows, {
            "status": "normalized" if removed_columns or normalized_time_columns else "already_canonical",
            "removed_redundant_columns": list(removed_columns),
            "normalized_time_columns": sorted(set(normalized_time_columns)),
            "metric": metric_profile,
        }
    metric = matched_metrics[0]
    if metric in working_columns:
        metric_profile = {"status": "already_semantic", "metric": metric}
        return working_columns, working_rows, {
            "status": "normalized" if removed_columns or normalized_time_columns else "already_canonical",
            "removed_redundant_columns": list(removed_columns),
            "normalized_time_columns": sorted(set(normalized_time_columns)),
            "metric": metric_profile,
        }
    numeric_columns = [
        column
        for column in working_columns
        if not column.endswith("_id")
        if any(
            isinstance(row.get(column), (int, float, Decimal))
            and not isinstance(row.get(column), bool)
            for row in working_rows
        )
        and all(
            row.get(column) is None
            or (
                isinstance(row.get(column), (int, float, Decimal))
                and not isinstance(row.get(column), bool)
            )
            for row in working_rows
        )
    ]
    if len(numeric_columns) != 1:
        metric_profile = {
            "status": "ambiguous_numeric_columns",
            "semantic_code": metric,
            "candidate_count": len(numeric_columns),
        }
        return working_columns, working_rows, {
            "status": "normalized" if removed_columns or normalized_time_columns else "already_canonical",
            "removed_redundant_columns": list(removed_columns),
            "normalized_time_columns": sorted(set(normalized_time_columns)),
            "metric": metric_profile,
        }
    source = numeric_columns[0]
    normalized_columns = tuple(metric if column == source else column for column in working_columns)
    normalized_rows = tuple(
        {metric if key == source else key: value for key, value in row.items()}
        for row in working_rows
    )
    metric_profile = {
        "status": "normalized",
        "semantic_code": metric,
        "source_alias": source,
    }
    return normalized_columns, normalized_rows, {
        "status": "normalized",
        "removed_redundant_columns": list(removed_columns),
        "normalized_time_columns": sorted(set(normalized_time_columns)),
        "metric": metric_profile,
    }


def _binding_hash(key: SQLBotSessionKey) -> str:
    raw = json.dumps(key.as_tuple(), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


class SQLBotEngine(QueryEngine):
    name = "sqlbot"
    version = "adapter-1.2.0/sqlbot-v1.10.0"

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        runtime_verified: bool | None = None,
        client: SQLBotClient | None = None,
        session_manager: SQLBotSessionManager | None = None,
        session_on_bind: Callable[[SQLBotSession], None] | None = None,
        policy_guard: SQLPolicyGuard | None = None,
        generated_sql_executor: GeneratedSQLExecutor | None = None,
    ):
        settings = get_settings()
        configured = SQLBotFeatureFlags.from_settings()
        self.flags = SQLBotFeatureFlags(
            enabled=configured.enabled if enabled is None else enabled,
            runtime_verified=(
                configured.runtime_verified
                if runtime_verified is None
                else runtime_verified
            ),
        )
        breaker = CircuitBreaker(
            settings.sqlbot_circuit_failure_threshold,
            settings.sqlbot_circuit_recovery_seconds,
        )
        self.client = client or SQLBotClient(
            settings.sqlbot_base_url,
            username_env_key=settings.sqlbot_username_env_key,
            password_env_key=settings.sqlbot_password_env_key,
            timeout_seconds=settings.sqlbot_timeout_seconds,
            breaker=breaker,
        )
        self.sessions = session_manager or SQLBotSessionManager()
        self.session_on_bind = session_on_bind
        self.policy_guard = policy_guard or guard_sqlbot_sql
        self.generated_sql_executor = generated_sql_executor

    def execute(
        self,
        request: QueryRequest,
        context: QueryContext | None = None,
    ) -> QueryResult:
        self.flags.require_runtime()
        if context is None:
            raise SQLBotEngineError(
                SQLBotErrorCode.NOT_CONFIGURED,
                "SQLBot 查询缺少 ACTIVE 版本上下文",
            )
        if context.cancelled and context.cancelled():
            raise SQLBotEngineError(
                SQLBotErrorCode.CANCELLED,
                "SQLBot 查询已取消",
            )
        if not all((
            context.scenario_version,
            context.semantic_version,
            context.semantic_model_version_id,
            context.dataset_version,
            context.dataset_version_id,
        )):
            raise SQLBotEngineError(
                SQLBotErrorCode.POLICY_DENIED,
                "SQLBot 查询缺少版本绑定",
            )
        requested_execution_mode = context.execution_mode
        context = replace(context, execution_mode="platform_readonly")
        started = perf_counter()
        timings: dict[str, int | None] = {
            "schema_retrieval_ms": 0,
            "prompt_build_ms": 0,
            "runtime_connection_ms": 0,
            "model_ttft_ms": None,
            "model_generation_ms": 0,
            "retry_ms": 0,
            "normalization_ms": 0,
            "guard_ms": 0,
            "execution_ms": 0,
            "answer_ms": 0,
        }
        key = SQLBotSessionKey(
            tenant_id=request.identity_context.tenant_id,
            workspace_id=request.identity_context.workspace_id,
            subject_id=request.identity_context.subject_id,
            conversation_id=context.conversation_id,
            scenario_id=request.scenario_id,
            scenario_version=context.scenario_version,
            semantic_version=context.semantic_version,
            dataset_version=context.dataset_version,
        )
        phase = perf_counter()
        retrieved = retrieve_schema(request.question, context)
        timings["schema_retrieval_ms"] = int((perf_counter() - phase) * 1000)
        governed_context = replace(
            context,
            allowed_relations=retrieved.relations,
            prompt_context={
                **context.prompt_context,
                **retrieved.as_prompt_context(),
                "scenario_id": request.scenario_id,
                "sql_examples": authorized_examples(
                    request.scenario_id,
                    retrieved.relations,
                    request.question,
                ),
            },
        )
        understanding = understand_query(request, governed_context)
        if understanding.status == "NEEDS_CLARIFICATION":
            raise SQLBotEngineError(
                SQLBotErrorCode.NEEDS_CLARIFICATION,
                understanding.clarification_question or "查询需要澄清",
            )
        if understanding.status == "REJECTED":
            raise SQLBotEngineError(
                SQLBotErrorCode.POLICY_DENIED,
                "query understanding rejected a high-risk request",
            )
        phase = perf_counter()
        session = self.sessions.get_or_create(
            key,
            self.client.create_session,
            on_bind=self.session_on_bind,
        )
        timings["runtime_connection_ms"] = int((perf_counter() - phase) * 1000)
        generation_attempts: list[dict] = []
        exact_example = exact_authorized_example(
            request.scenario_id, retrieved.relations, request.question
        )
        generation_attempt = 1
        generation_started = perf_counter()
        try:
            raw_payload, prompt_ms, model_ms, prompt_profile = self._ask_with_single_rebuild(
                request, governed_context, key, session
            )
            timings["prompt_build_ms"] = prompt_ms
            timings["model_generation_ms"] = model_ms
        except SQLBotEngineError as generation_error:
            transport_fallback_codes = {
                SQLBotErrorCode.TIMEOUT,
                SQLBotErrorCode.UPSTREAM_UNAVAILABLE,
                SQLBotErrorCode.CIRCUIT_OPEN,
            }
            if (
                exact_example is None
                or generation_error.code not in transport_fallback_codes
            ):
                raise
            timings["model_generation_ms"] = int(
                (perf_counter() - generation_started) * 1000
            )
            generation_attempts.append({
                "generation_attempt": 1,
                "sql_hash": None,
                "guard_result": "NOT_EXECUTED_TRANSPORT_ERROR",
                "error": str(generation_error.code),
            })
            raw_payload = {"sql": exact_example["sql"]}
            prompt_profile = {
                "repair": {
                    "mode": "governed_exact_example_fallback",
                    "external_model_call": True,
                    "reason": str(generation_error.code),
                }
            }
            generation_attempt = 2

        def prepare_and_guard(payload: dict, attempt: int):
            phase = perf_counter()
            candidate = parse_response(
                payload,
                max_rows=min(context.max_rows, request.limits.get("rows", context.max_rows)),
            )
            limited = apply_limit_policy(
                candidate.sql,
                max_limit=min(context.max_rows, request.limits.get("rows", context.max_rows)),
            )
            candidate = replace(
                candidate,
                sql=limited.sql,
                warnings=candidate.warnings + limited.warnings,
            )
            timings["normalization_ms"] += int((perf_counter() - phase) * 1000)
            phase = perf_counter()
            try:
                self.policy_guard(candidate.sql, governed_context)
                decision = validate_generated_sql(candidate.sql, governed_context)
            except (QueryRejected, SQLBotEngineError) as exc:
                timings["guard_ms"] += int((perf_counter() - phase) * 1000)
                error = (
                    f"{exc.code}:{exc.message}"
                    if isinstance(exc, SQLBotEngineError)
                    else f"QUERY_GUARD_REJECTED:{exc}"
                )
                generation_attempts.append({
                    "generation_attempt": attempt,
                    "sql_hash": hashlib.sha256(candidate.sql.encode()).hexdigest(),
                    "guard_result": "REJECTED",
                    "error": error,
                })
                raise
            timings["guard_ms"] += int((perf_counter() - phase) * 1000)
            generation_attempts.append({
                "generation_attempt": attempt,
                "sql_hash": hashlib.sha256(decision.normalized_sql.encode()).hexdigest(),
                "guard_result": "PASSED",
                "error": None,
            })
            return candidate, decision

        try:
            parsed, policy_decision = prepare_and_guard(raw_payload, generation_attempt)
        except (QueryRejected, SQLBotEngineError) as first_error:
            if generation_attempt == 2:
                raise SQLBotEngineError(
                    SQLBotErrorCode.POLICY_DENIED,
                    str(first_error),
                ) from first_error
            if not generation_attempts:
                if (
                    exact_example is None
                    or not isinstance(first_error, SQLBotEngineError)
                    or first_error.code not in {
                        SQLBotErrorCode.MODEL_REFUSAL,
                        SQLBotErrorCode.RESPONSE_INVALID,
                    }
                ):
                    raise
                generation_attempts.append({
                    "generation_attempt": 1,
                    "sql_hash": None,
                    "guard_result": "REFUSED_OR_INVALID",
                    "error": str(first_error.code),
                })
            if isinstance(first_error, SQLBotEngineError) and first_error.code not in {
                SQLBotErrorCode.POLICY_DENIED,
                SQLBotErrorCode.RESPONSE_INVALID,
                SQLBotErrorCode.MODEL_REFUSAL,
            }:
                raise
            repair_started = perf_counter()
            if exact_example is not None:
                upstream_record_id = None
                token_usage = None
                try:
                    first_parsed = parse_response(
                        raw_payload,
                        max_rows=min(
                            context.max_rows,
                            request.limits.get("rows", context.max_rows),
                        ),
                    )
                    upstream_record_id = first_parsed.upstream_record_id
                    token_usage = first_parsed.token_usage
                except SQLBotEngineError:
                    pass
                raw_payload = {
                    "sql": exact_example["sql"],
                    "record_id": upstream_record_id,
                    "token_usage": token_usage,
                }
                repair_prompt_profile = {
                    "mode": "governed_exact_example_fallback",
                    "external_model_call": False,
                }
            else:
                rejected_sql = generation_attempts[-1]["sql_hash"]
                # The model receives the original SQL text, but evidence persists only its hash.
                first_parsed = parse_response(
                    raw_payload,
                    max_rows=min(context.max_rows, request.limits.get("rows", context.max_rows)),
                )
                guard_error = generation_attempts[-1]["error"]
                repair_question = build_guard_repair_question(
                    request.question,
                    original_sql=first_parsed.sql,
                    guard_error=guard_error,
                    prompt_context=governed_context.prompt_context,
                )
                raw_payload, repair_prompt_ms, repair_model_ms, repair_prompt_profile = self._ask_with_single_rebuild(
                    request,
                    governed_context,
                    key,
                    session,
                    question_override=repair_question,
                )
                timings["prompt_build_ms"] += repair_prompt_ms
                timings["model_generation_ms"] += repair_model_ms
            timings["retry_ms"] = int((perf_counter() - repair_started) * 1000)
            prompt_profile["repair"] = repair_prompt_profile
            try:
                parsed, policy_decision = prepare_and_guard(raw_payload, 2)
            except (QueryRejected, SQLBotEngineError) as repair_error:
                raise SQLBotEngineError(
                    SQLBotErrorCode.POLICY_DENIED,
                    str(repair_error),
                ) from repair_error

        if parsed.token_usage is None and parsed.upstream_record_id is not None:
            parsed = replace(
                parsed,
                token_usage=self.client.record_usage(
                    parsed.upstream_record_id,
                    session.access_token,
                ),
            )
        parsed = replace(parsed, sql=policy_decision.normalized_sql)
        columns, rows = parsed.columns, parsed.rows
        if context.execution_mode in {"generate_only", "platform_readonly"}:
            if self.generated_sql_executor is None:
                raise SQLBotEngineError(
                    SQLBotErrorCode.NOT_CONFIGURED,
                    "SQLBot 生成 SQL 的只读执行器未配置",
                )
            phase = perf_counter()
            columns, rows = self.generated_sql_executor(
                parsed.sql, request, governed_context
            )
            timings["execution_ms"] = int((perf_counter() - phase) * 1000)
        columns, rows, result_normalization = _normalize_result_contract(
            columns,
            rows,
            understanding.matched_metrics,
            understanding.matched_dimensions,
        )
        if len(rows) > context.max_rows:
            raise SQLBotEngineError(
                SQLBotErrorCode.POLICY_DENIED,
                "SQLBot 结果超过平台行数上限",
            )
        phase = perf_counter()
        result_validation = validate_result(
            columns, rows, governed_context, policy_decision
        )
        timings["answer_ms"] = int((perf_counter() - phase) * 1000)
        run_id = context.run_id or f"SQLBOT-{uuid4()}"
        evidence = {
            "data_classification": context.data_classification,
            "source": "sqlbot_adapter",
            "upstream_version": "v1.10.0",
            "execution_mode": context.execution_mode,
            "requested_execution_mode": requested_execution_mode,
            "upstream_sql_execution": False,
            "session_binding_hash": _binding_hash(key),
            "upstream_record_id": parsed.upstream_record_id,
            "token_usage": parsed.token_usage,
            "scenario_version": context.scenario_version,
            "semantic_version": context.semantic_version,
            "semantic_model_version_id": context.semantic_model_version_id,
            "dataset_version": context.dataset_version,
            "dataset_version_id": context.dataset_version_id,
            "query_guard": "passed",
            "schema_catalog_version": retrieved.catalog_version,
            "schema_catalog_hash": retrieved.catalog_hash,
            "schema_retrieval_relations": list(retrieved.relations),
            "query_understanding": understanding.as_dict(),
            "metrics": list(understanding.matched_metrics),
            "dimensions": list(understanding.matched_dimensions),
            "time_range": _extract_sql_time_range(parsed.sql),
            "metric_values": {
                metric: rows[0][metric]
                for metric in understanding.matched_metrics
                if len(rows) == 1 and metric in rows[0]
            },
            "result_contract_normalization": result_normalization,
            "prompt_profile": prompt_profile,
            "schema_profile": {
                "relation_count": len(retrieved.relations),
                "field_count": sum(len(fields) for fields in retrieved.relations.values()),
                "relationship_count": len(retrieved.relationships),
                "metric_count": len(retrieved.metrics),
                "dimension_count": len(retrieved.dimensions),
            },
            "sql_policy_checks": list(policy_decision.checks),
            "join_count": policy_decision.join_count,
            "row_limit": policy_decision.row_limit,
            "result_guard": result_validation,
            "answer_guard": "passed",
            "generation_attempts": generation_attempts,
            "repair_used": len(generation_attempts) == 2,
            "governed_exact_example_fallback": (
                prompt_profile.get("repair", {}).get("mode")
                == "governed_exact_example_fallback"
            ),
            "governed_exact_example_fallback_reason": prompt_profile.get(
                "repair", {}
            ).get("reason"),
            "latency_profile": {
                **timings,
                "total_ms": int((perf_counter() - started) * 1000),
            },
        }
        return QueryResult(
            engine=self.name,
            engine_version=self.version,
            scenario=request.scenario_id,
            scenario_version=context.scenario_version,
            semantic_version=context.semantic_version,
            dataset_version=context.dataset_version,
            sql=parsed.sql,
            columns=columns,
            rows=rows,
            chart_spec=parsed.chart_spec,
            evidence=evidence,
            warnings=parsed.warnings,
            execution_time=int((perf_counter() - started) * 1000),
            trace_id=request.identity_context.request_id,
            run_id=run_id,
            status="completed",
        )

    def _ask_with_single_rebuild(
        self,
        request: QueryRequest,
        context: QueryContext,
        key: SQLBotSessionKey,
        session,
        *,
        question_override: str | None = None,
    ) -> tuple[dict, int, int, dict]:
        prompt_started = perf_counter()
        payload = map_question_request(
            request,
            context,
            session,
            question_override=question_override,
        )
        question = payload["question"]
        prompt_profile = {
            "characters": len(question),
            "utf8_bytes": len(question.encode("utf-8")),
        }
        prompt_ms = int((perf_counter() - prompt_started) * 1000)
        model_started = perf_counter()
        try:
            response = self.client.generate_sql(payload)
            return (
                response,
                prompt_ms,
                int((perf_counter() - model_started) * 1000),
                prompt_profile,
            )
        except SQLBotEngineError as exc:
            if exc.code != SQLBotErrorCode.SESSION_INVALID:
                raise
        rebuilt = self.sessions.get_or_create(
            key,
            self.client.create_session,
            force_rebuild=True,
            on_bind=self.session_on_bind,
        )
        prompt_started = perf_counter()
        payload = map_question_request(
            request,
            context,
            rebuilt,
            question_override=question_override,
        )
        question = payload["question"]
        prompt_profile = {
            "characters": len(question),
            "utf8_bytes": len(question.encode("utf-8")),
            "session_rebuilt": True,
        }
        prompt_ms += int((perf_counter() - prompt_started) * 1000)
        response = self.client.generate_sql(payload)
        return (
            response,
            prompt_ms,
            int((perf_counter() - model_started) * 1000),
            prompt_profile,
        )

    def health_check(self) -> dict:
        if not self.flags.enabled:
            status = "DISABLED"
        elif not self.flags.runtime_verified:
            status = "RUNTIME_PENDING"
        else:
            status = self.client.health_check().status
        return {
            "engine": self.name,
            "version": self.version,
            "enabled": self.flags.enabled,
            "runtime_verified": self.flags.runtime_verified,
            "status": status,
        }
