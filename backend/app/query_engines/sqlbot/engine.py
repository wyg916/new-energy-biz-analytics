import hashlib
import json
from dataclasses import replace
from time import perf_counter
from typing import Callable
from uuid import uuid4

from app.chatbi.guard import guard_sqlbot_sql
from app.core.config import get_settings
from app.platform.query_engine import QueryContext, QueryEngine, QueryRequest, QueryResult
from app.query_engines.sqlbot.client import SQLBotClient
from app.query_engines.sqlbot.contracts import SQLBotSessionKey
from app.query_engines.sqlbot.error_mapper import (
    SQLBotEngineError,
    SQLBotErrorCode,
)
from app.query_engines.sqlbot.feature_flags import SQLBotFeatureFlags
from app.query_engines.sqlbot.health import CircuitBreaker
from app.query_engines.sqlbot.limit_policy import apply_limit_policy
from app.query_engines.sqlbot.policy import SQLPolicyDecision, validate_generated_sql
from app.query_engines.sqlbot.request_mapper import map_question_request
from app.query_engines.sqlbot.response_parser import parse_response
from app.query_engines.sqlbot.result_guard import validate_result
from app.query_engines.sqlbot.schema_catalog import retrieve_schema
from app.query_engines.sqlbot.session_manager import SQLBotSessionManager


GeneratedSQLExecutor = Callable[
    [str, QueryRequest, QueryContext],
    tuple[tuple[str, ...], tuple[dict, ...]],
]
SQLPolicyGuard = Callable[[str, QueryContext], None]


def _binding_hash(key: SQLBotSessionKey) -> str:
    raw = json.dumps(key.as_tuple(), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


class SQLBotEngine(QueryEngine):
    name = "sqlbot"
    version = "adapter-1.1.0/sqlbot-v1.8.0"

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        runtime_verified: bool | None = None,
        client: SQLBotClient | None = None,
        session_manager: SQLBotSessionManager | None = None,
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
        session = self.sessions.get_or_create(key, self.client.create_session)
        retrieved = retrieve_schema(request.question, context)
        governed_context = replace(
            context,
            allowed_relations=retrieved.relations,
            prompt_context={
                **context.prompt_context,
                **retrieved.as_prompt_context(),
                "scenario_id": request.scenario_id,
                "sql_examples": context.prompt_context.get("sql_examples", []),
                "time_dimensions": context.prompt_context.get("time_dimensions", []),
            },
        )
        raw_payload = self._ask_with_single_rebuild(
            request, governed_context, key, session
        )
        parsed = parse_response(
            raw_payload,
            max_rows=min(context.max_rows, request.limits.get("rows", context.max_rows)),
        )
        limited = apply_limit_policy(
            parsed.sql,
            max_limit=min(context.max_rows, request.limits.get("rows", context.max_rows)),
        )
        parsed = replace(
            parsed,
            sql=limited.sql,
            warnings=parsed.warnings + limited.warnings,
        )
        if parsed.token_usage is None and parsed.upstream_record_id is not None:
            parsed = replace(
                parsed,
                token_usage=self.client.record_usage(
                    parsed.upstream_record_id,
                    session.access_token,
                ),
            )
        self.policy_guard(parsed.sql, governed_context)
        policy_decision: SQLPolicyDecision = validate_generated_sql(
            parsed.sql, governed_context
        )
        parsed = replace(parsed, sql=policy_decision.normalized_sql)
        columns, rows = parsed.columns, parsed.rows
        if context.execution_mode in {"generate_only", "platform_readonly"}:
            if self.generated_sql_executor is None:
                raise SQLBotEngineError(
                    SQLBotErrorCode.NOT_CONFIGURED,
                    "SQLBot 生成 SQL 的只读执行器未配置",
                )
            columns, rows = self.generated_sql_executor(
                parsed.sql, request, governed_context
            )
        if len(rows) > context.max_rows:
            raise SQLBotEngineError(
                SQLBotErrorCode.POLICY_DENIED,
                "SQLBot 结果超过平台行数上限",
            )
        result_validation = validate_result(
            columns, rows, governed_context, policy_decision
        )
        run_id = context.run_id or f"SQLBOT-{uuid4()}"
        evidence = {
            "data_classification": "simulated",
            "source": "sqlbot_adapter",
            "upstream_version": "v1.8.0",
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
            "sql_policy_checks": list(policy_decision.checks),
            "join_count": policy_decision.join_count,
            "row_limit": policy_decision.row_limit,
            "result_guard": result_validation,
            "answer_guard": "passed",
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
    ) -> dict:
        try:
            return self.client.generate_sql(map_question_request(request, context, session))
        except SQLBotEngineError as exc:
            if exc.code != SQLBotErrorCode.SESSION_INVALID:
                raise
        rebuilt = self.sessions.get_or_create(
            key,
            self.client.create_session,
            force_rebuild=True,
        )
        return self.client.generate_sql(map_question_request(request, context, rebuilt))

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
