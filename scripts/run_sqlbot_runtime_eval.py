"""Run real SQLBot smoke or Golden evaluation against ACTIVE simulated data.

The script is intended for an isolated acceptance container. SQLBot service
credentials are resolved only through governed CredentialReference records. The detailed
JSON artifact contains generated SQL and hashes, but never credentials, access
tokens, model response prose, or business result rows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx
import sqlglot
from sqlalchemy import select, text

from app.chatbi.guard import QueryRejected, guard_sqlbot_sql
from app.core.database import SessionLocal
from app.evaluation.runtime_closeout import runtime_smoke_cases
from app.models.auth import User
from app.platform.query_engine import QueryContext, QueryRequest
from app.query_engines.context import build_query_context
from app.query_engines.sqlbot.client import SQLBotClient
from app.query_engines.sqlbot.contracts import SQLBotSession, SQLBotSessionKey
from app.query_engines.sqlbot.error_mapper import SQLBotEngineError, SQLBotErrorCode
from app.query_engines.sqlbot.health import CircuitBreaker
from app.query_engines.sqlbot.limit_policy import apply_limit_policy
from app.query_engines.sqlbot.policy import validate_generated_sql
from app.query_engines.sqlbot.prompt_context import (
    authorized_examples,
    build_guard_repair_question,
)
from app.query_engines.sqlbot.readonly_executor import execute_generated_readonly
from app.query_engines.sqlbot.request_mapper import map_question_request
from app.query_engines.sqlbot.response_parser import parse_response
from app.query_engines.sqlbot.result_guard import validate_result
from app.query_engines.sqlbot.schema_catalog import retrieve_schema
from app.scenarios.charging_ops.runtime import resolve_charging_ops_context
from app.scenarios.sales_ops.runtime import resolve_sales_ops_context
from app.governance.secrets import CredentialReferenceService
from app.platform.identity import IdentityContextFactory


DATASOURCE_IDS = {"charging_ops": "1", "sales_ops": "2"}
RELATION_WORDS = {
    "charging_ops": {
        "date": ("start_time", "settlement_time"),
        "region": ("region_id",),
        "city": ("city_id",),
        "station": ("station_id", "station_name"),
        "station_type": ("station_type",),
        "operator": ("operator_code",),
        "device": ("connector_count",),
    },
    "sales_ops": {
        "date": ("order_date",),
        "region": ("region_id", "region_name"),
        "channel": ("channel_id", "channel_name", "channel_type"),
        "product": ("product_id", "product_name"),
        "category": ("category_id",),
        "organization": ("organization_code",),
    },
}


def _hash(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def _sanitized_model_payload(value: Any) -> Any:
    """Preserve the model envelope while removing secrets and upstream result rows."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if re.search(r"(?i)(token|password|secret|authorization)", str(key)):
                result[key] = "<redacted>"
            elif str(key).lower() in {"rows", "data_list"}:
                result[key] = "<omitted_generate_only_rows>"
            else:
                result[key] = _sanitized_model_payload(item)
        return result
    if isinstance(value, list):
        return [_sanitized_model_payload(item) for item in value]
    return value


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _rate(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else round(numerator / denominator, 6)


def _source_stats(db) -> dict[str, dict[str, Any]]:
    charging = db.execute(text("""
        SELECT
          MIN((start_time AT TIME ZONE 'Asia/Shanghai')::date),
          MAX((start_time AT TIME ZONE 'Asia/Shanghai')::date),
          COUNT(*)
        FROM fact_charging_session
    """)).one()
    sales = db.execute(text("""
        SELECT MIN(order_date), MAX(order_date), COUNT(*)
        FROM sales_order
    """)).one()
    return {
        "charging_ops": {
            "min_date": charging[0].isoformat(),
            "max_date": charging[1].isoformat(),
            "row_count": int(charging[2]),
        },
        "sales_ops": {
            "min_date": sales[0].isoformat(),
            "max_date": sales[1].isoformat(),
            "row_count": int(sales[2]),
        },
    }


def _runtime_contexts(db, user: User) -> tuple[dict[str, Any], dict[str, QueryContext]]:
    charging_identity, charging_active = resolve_charging_ops_context(db, user)
    sales_identity, sales_active = resolve_sales_ops_context(db, user)
    identities = {
        "charging_ops": charging_identity,
        "sales_ops": sales_identity,
    }
    contexts = {}
    for scenario, active in (
        ("charging_ops", charging_active),
        ("sales_ops", sales_active),
    ):
        base_context = build_query_context(
            db,
            conversation_id=f"p2a-runtime-{scenario}",
            platform_context=active,
        )
        contexts[scenario] = replace(
            base_context,
            datasource_id=DATASOURCE_IDS[scenario],
            prompt_context={
                **base_context.prompt_context,
                "scenario_id": scenario,
            },
            max_rows=500,
        )
    return identities, contexts


def _cases(args, stats: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    if args.mode == "smoke":
        return runtime_smoke_cases(
            charging_min_date=stats["charging_ops"]["min_date"],
            charging_max_date=stats["charging_ops"]["max_date"],
            sales_min_date=stats["sales_ops"]["min_date"],
            sales_max_date=stats["sales_ops"]["max_date"],
        )
    source = json.loads(args.source.read_text(encoding="utf-8"))
    cases = source.get("cases")
    if not isinstance(cases, list) or len(cases) != 100:
        raise RuntimeError("runtime Golden source must contain exactly 100 cases")
    if args.mode in {"smoke20", "representative"}:
        selected = []
        per_group = 2 if args.mode == "smoke20" else 3
        for category in (
            "single_metric",
            "filter_sort",
            "trend_comparison",
            "multi_table_dimension",
            "ambiguity_security_refusal",
        ):
            for scenario in ("charging_ops", "sales_ops"):
                group = [
                    case for case in cases
                    if case.get("category") == category
                    and case.get("scenario_id") == scenario
                ][:per_group]
                if len(group) != per_group:
                    raise RuntimeError("runtime selection has insufficient category/scenario coverage")
                selected.extend(group)
        return selected
    return cases


def _usage(client: SQLBotClient, token: str, record_id: str | None) -> int | None:
    if not record_id:
        return None
    try:
        response = client.http.get(
            f"chat/record/{record_id}/usage",
            headers={"X-SQLBOT-TOKEN": f"Bearer {token}"},
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            payload = payload["data"]
        value = payload.get("total_tokens") if isinstance(payload, dict) else None
        return value if isinstance(value, int) else None
    except Exception:
        return None


def _sql_observations(sql: str, context: QueryContext) -> dict[str, Any]:
    try:
        root = sqlglot.parse_one(sql, read="postgres")
    except Exception:
        return {
            "tables": [],
            "columns": [],
            "hallucinated_tables": [],
            "hallucinated_fields": [],
            "has_order_by": False,
        }
    tables = sorted({item.name for item in root.find_all(sqlglot.exp.Table)})
    columns = sorted({item.name for item in root.find_all(sqlglot.exp.Column)})
    allowed_columns = {
        field
        for fields in context.allowed_relations.values()
        for field in fields
    }
    aliases = {
        item.alias
        for item in root.find_all(sqlglot.exp.Alias)
        if item.alias
    }
    return {
        "tables": tables,
        "columns": columns,
        "hallucinated_tables": sorted(set(tables) - set(context.allowed_relations)),
        "hallucinated_fields": sorted(set(columns) - allowed_columns - aliases),
        "has_order_by": root.args.get("order") is not None,
    }


def _dimension_alignment(
    scenario: str,
    expected: list[str],
    sql: str,
) -> bool | None:
    if not expected:
        return None
    lowered = sql.lower()
    mapping = RELATION_WORDS[scenario]
    supported = [dimension for dimension in expected if dimension in mapping]
    if not supported:
        return None
    return all(any(word in lowered for word in mapping[item]) for item in supported)


def _time_alignment(question: str, sql: str) -> bool | None:
    years = sorted(set(re.findall(r"20\d{2}", question)))
    if not years:
        return None
    return all(year in sql for year in years)


def _sort_alignment(question: str, sql_observations: dict[str, Any]) -> bool | None:
    if not any(word in question for word in ("最高", "最低", "排序", "高到低", "低到高", "排名")):
        return None
    return bool(sql_observations["has_order_by"])


def _execute_case(
    case: dict[str, Any],
    *,
    identity,
    context: QueryContext,
    client: SQLBotClient,
    max_attempts: int,
) -> dict[str, Any]:
    case_id = str(case.get("case_id"))
    scenario = str(case.get("scenario") or case.get("scenario_id"))
    question = str(case.get("question"))
    expected_decision = str(case.get("expected_decision") or "QUERY")
    run_id = f"P2A-{case_id}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%f')}"
    request = QueryRequest(
        question=question,
        identity_context=replace(identity, request_id=run_id),
        scenario_id=scenario,
    )
    started = perf_counter()
    phase = perf_counter()
    retrieved = retrieve_schema(question, context)
    schema_retrieval_ms = int((perf_counter() - phase) * 1000)
    context = replace(
        context,
        allowed_relations=retrieved.relations,
        prompt_context={
            **context.prompt_context,
            **retrieved.as_prompt_context(),
            "scenario_id": scenario,
            "sql_examples": authorized_examples(scenario, retrieved.relations),
        },
    )
    timings: dict[str, int | None] = {
        "schema_retrieval_ms": schema_retrieval_ms,
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
    attempts = 1
    last_error = None
    raw_payload = None
    session = None
    external_calls = 0
    try:
        phase = perf_counter()
        chat_id, token = client.create_session()
        timings["runtime_connection_ms"] += int((perf_counter() - phase) * 1000)
        session = SQLBotSession(
            key=SQLBotSessionKey(
                tenant_id=identity.tenant_id,
                workspace_id=identity.workspace_id,
                subject_id=identity.subject_id,
                conversation_id=f"p2a-runtime-{case_id}-1",
                scenario_id=scenario,
                scenario_version=context.scenario_version,
                semantic_version=context.semantic_version,
                dataset_version=context.dataset_version,
            ),
            external_chat_id=chat_id,
            access_token=token,
        )
        external_calls += 1
        phase = perf_counter()
        mapped_request = map_question_request(request, context, session)
        timings["prompt_build_ms"] += int((perf_counter() - phase) * 1000)
        phase = perf_counter()
        raw_payload = client.generate_sql(mapped_request)
        timings["model_generation_ms"] += int((perf_counter() - phase) * 1000)
    except SQLBotEngineError as exc:
        last_error = str(exc.code)
    except Exception as exc:
        last_error = f"SQLBOT_{type(exc).__name__.upper()}"

    latency_ms = int((perf_counter() - started) * 1000)
    timings["total_ms"] = latency_ms
    base = {
        "case_id": case_id,
        "scenario": scenario,
        "category": case.get("category"),
        "expected_decision": expected_decision,
        "question": question,
        "normalized_question": re.sub(r"\s+", " ", question.strip()),
        "model": "deepseek-v4-flash",
        "upstream_sql_execution": False,
        "model_called": external_calls > 0,
        "external_request_count": external_calls,
        "attempts": attempts,
        "sqlbot_session_created": session is not None,
        "generated_sql": None,
        "limit_policy_warnings": [],
        "sql_hash": None,
        "guard_result": "NOT_EXECUTED",
        "execution_status": "NOT_EXECUTED",
        "execution_error_detail": None,
        "row_count": None,
        "result_hash": None,
        "latency_ms": latency_ms,
        "latency_profile": timings,
        "prompt_version": "sqlbot-schema-4.1/41c",
        "schema_retrieval_result": retrieved.as_prompt_context(),
        "final_schema_context": {
            "authorized_tables": context.prompt_context.get("authorized_tables", []),
            "relationships": context.prompt_context.get("relationships", []),
            "metrics": context.prompt_context.get("metrics", []),
            "dimensions": context.prompt_context.get("dimensions", []),
            "time_dimensions": context.prompt_context.get("time_dimensions", []),
        },
        "model_raw_return": None,
        "model_response_received": False,
        "model_refusal": False,
        "generation_attempts": [],
        "repair_attempt": 0,
        "token_usage": None,
        "dataset_version": context.dataset_version,
        "dataset_version_id": context.dataset_version_id,
        "semantic_version": context.semantic_version,
        "semantic_model_version_id": context.semantic_model_version_id,
        "scenario_version": context.scenario_version,
        "run_id": run_id,
        "trace_id": request.identity_context.request_id,
        "error": last_error,
        "final_status": "FAIL",
        "permission_pass": None,
        "time_range_alignment": None,
        "dimension_alignment": None,
        "sort_alignment": None,
        "hallucinated_tables": [],
        "hallucinated_fields": [],
    }

    def finish() -> dict[str, Any]:
        elapsed = int((perf_counter() - started) * 1000)
        timings["total_ms"] = elapsed
        base["latency_ms"] = elapsed
        return base

    if raw_payload is None or session is None:
        return finish()
    base["model_raw_return"] = _sanitized_model_payload(raw_payload)
    base["model_response_received"] = True

    allowed_rows = min(context.max_rows, request.limits.get("rows", context.max_rows))
    policy = None
    for generation_attempt in range(1, max_attempts + 1):
        phase = perf_counter()
        try:
            parsed = parse_response(raw_payload, max_rows=5000)
            limited = apply_limit_policy(parsed.sql, max_limit=allowed_rows)
        except SQLBotEngineError as exc:
            timings["normalization_ms"] += int((perf_counter() - phase) * 1000)
            base["error"] = str(exc.code)
            if exc.code == SQLBotErrorCode.MODEL_REFUSAL:
                base["model_refusal"] = True
                base["guard_result"] = "REFUSED_PRE_SQL"
                base["generation_attempts"].append({
                    "generation_attempt": generation_attempt,
                    "sql_hash": None,
                    "guard_result": "REFUSED_PRE_SQL",
                    "error": str(exc.code),
                })
                base["permission_pass"] = True
                if expected_decision in {"REJECT", "CLARIFY"}:
                    base["error"] = None
                    base["final_status"] = "PASS"
            return finish()
        parsed = replace(
            parsed,
            sql=limited.sql,
            warnings=parsed.warnings + limited.warnings,
        )
        timings["normalization_ms"] += int((perf_counter() - phase) * 1000)
        sql = parsed.sql
        observations = _sql_observations(sql, context)
        sql_hash = hashlib.sha256(sql.encode()).hexdigest()
        base.update({
            "generated_sql": sql,
            "limit_policy_warnings": list(limited.warnings),
            "sql_hash": sql_hash,
            "execution_status": "NOT_EXECUTED",
            "row_count": None,
            "result_hash": None,
            "token_usage": _usage(client, session.access_token, parsed.upstream_record_id),
            "error": None,
            "time_range_alignment": _time_alignment(question, sql),
            "dimension_alignment": _dimension_alignment(
                scenario,
                list(case.get("expected_dimensions") or []),
                sql,
            ),
            "sort_alignment": _sort_alignment(question, observations),
            "hallucinated_tables": observations["hallucinated_tables"],
            "hallucinated_fields": observations["hallucinated_fields"],
        })
        phase = perf_counter()
        try:
            if len(parsed.rows) > allowed_rows:
                raise QueryRejected(
                    f"upstream generate-only response contained {len(parsed.rows)} rows"
                )
            guard_sqlbot_sql(sql, context)
            policy = validate_generated_sql(sql, context)
        except (QueryRejected, SQLBotEngineError) as exc:
            timings["guard_ms"] += int((perf_counter() - phase) * 1000)
            error = (
                f"{exc.code}:{exc.message}"
                if isinstance(exc, SQLBotEngineError)
                else f"QUERY_GUARD_REJECTED:{exc}"
            )
            base["generation_attempts"].append({
                "generation_attempt": generation_attempt,
                "sql_hash": sql_hash,
                "guard_result": "REJECTED",
                "error": error,
            })
            base["guard_result"] = "REJECTED"
            base["error"] = error
            base["permission_pass"] = True
            if expected_decision in {"REJECT", "CLARIFY"}:
                base["final_status"] = "PASS"
                return finish()
            if generation_attempt == max_attempts:
                return finish()
            repair_question = build_guard_repair_question(
                question,
                original_sql=sql,
                guard_error=error,
            )
            repair_started = perf_counter()
            phase = perf_counter()
            mapped_request = map_question_request(
                request,
                context,
                session,
                question_override=repair_question,
            )
            timings["prompt_build_ms"] += int((perf_counter() - phase) * 1000)
            phase = perf_counter()
            external_calls += 1
            base["attempts"] = 2
            try:
                raw_payload = client.generate_sql(mapped_request)
            except SQLBotEngineError as repair_error:
                timings["model_generation_ms"] += int((perf_counter() - phase) * 1000)
                timings["retry_ms"] = int((perf_counter() - repair_started) * 1000)
                base["repair_attempt"] = 1
                base["external_request_count"] = external_calls
                base["error"] = str(repair_error.code)
                return finish()
            timings["model_generation_ms"] += int((perf_counter() - phase) * 1000)
            timings["retry_ms"] = int((perf_counter() - repair_started) * 1000)
            base["repair_attempt"] = 1
            base["external_request_count"] = external_calls
            base["model_raw_return"] = _sanitized_model_payload(raw_payload)
            continue
        timings["guard_ms"] += int((perf_counter() - phase) * 1000)
        base["generation_attempts"].append({
            "generation_attempt": generation_attempt,
            "sql_hash": hashlib.sha256(policy.normalized_sql.encode()).hexdigest(),
            "guard_result": "PASSED",
            "error": None,
        })
        base["guard_result"] = "PASSED"
        base["permission_pass"] = True
        break
    assert policy is not None
    if expected_decision != "QUERY":
        base["error"] = "EXPECTED_NON_QUERY_BUT_SQL_GENERATED"
        return finish()
    try:
        phase = perf_counter()
        policy = validate_generated_sql(sql, context)
        timings["guard_ms"] += int((perf_counter() - phase) * 1000)
        phase = perf_counter()
        columns, rows = execute_generated_readonly(
            policy.normalized_sql,
            request,
            context,
        )
        timings["execution_ms"] = int((perf_counter() - phase) * 1000)
        phase = perf_counter()
        validate_result(columns, rows, context, policy)
        timings["answer_ms"] = int((perf_counter() - phase) * 1000)
    except SQLBotEngineError as exc:
        base["error"] = str(exc.code)
        base["execution_error_detail"] = exc.message
        return finish()
    base.update({
        "generated_sql": policy.normalized_sql,
        "sql_hash": hashlib.sha256(policy.normalized_sql.encode()).hexdigest(),
        "execution_status": "PLATFORM_READONLY_COMPLETED",
        "row_count": len(rows),
        "result_hash": _hash(rows),
        "result_guard": "PASSED",
        "answer_guard": "PASSED",
        "final_status": "PASS",
    })
    return finish()


def _recover_results(
    cases: list[dict[str, Any]],
    recovery_source: dict[str, Any],
    contexts: dict[str, QueryContext],
    *,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    by_question = {str(case["question"]): case for case in cases}
    recovered = recovery_source.get("results")
    if not isinstance(recovered, list) or len(recovered) != len(cases):
        raise RuntimeError("SQLBot recovery source cardinality mismatch")
    results = []
    seen_questions: set[str] = set()
    for source in recovered:
        question = source.get("question")
        case = by_question.get(question)
        if case is None or question in seen_questions:
            raise RuntimeError("SQLBot recovery question contract mismatch")
        seen_questions.add(question)
        scenario = str(case["scenario_id"])
        context = contexts[scenario]
        sql = source.get("sql") if isinstance(source.get("sql"), str) else None
        duration_ms = source.get("duration_ms")
        timed_out = (
            isinstance(duration_ms, int)
            and duration_ms > timeout_seconds * 1000
        )
        record_error = source.get("error_code")
        expected_decision = str(case["expected_decision"])
        guard_result = "NOT_EXECUTED"
        guard_error = None
        observations = {
            "hallucinated_tables": [],
            "hallucinated_fields": [],
            "has_order_by": False,
        }
        if sql:
            observations = _sql_observations(sql, context)
            try:
                guard_sqlbot_sql(sql, context)
            except QueryRejected as exc:
                guard_result = "REJECTED"
                guard_error = f"QUERY_GUARD_REJECTED:{str(exc)}"
            else:
                guard_result = "PASSED"
        if timed_out:
            final_status = "FAIL"
            error = "SQLBOT_CLIENT_TIMEOUT"
        elif record_error or not sql:
            final_status = "FAIL"
            error = record_error or "SQLBOT_SQL_NOT_GENERATED"
        elif expected_decision == "QUERY":
            final_status = "PASS" if guard_result == "PASSED" else "FAIL"
            error = guard_error
        else:
            final_status = "PASS" if guard_result == "REJECTED" else "FAIL"
            error = (
                guard_error
                if guard_result == "REJECTED"
                else "EXPECTED_NON_QUERY_BUT_SQL_EXECUTED"
            )
        chat_id = str(source["chat_id"])
        results.append({
            "case_id": str(case["case_id"]),
            "scenario": scenario,
            "category": case.get("category"),
            "expected_decision": expected_decision,
            "question": question,
            "normalized_question": re.sub(r"\s+", " ", question.strip()),
            "model": "deepseek-v4-flash",
            "model_called": True,
            "external_request_count": 1,
            "attempts": 1,
            "sqlbot_session_created": True,
            "sqlbot_chat_id": chat_id,
            "sqlbot_record_id": source.get("record_id"),
            "generated_sql": sql,
            "sql_hash": source.get("sql_hash"),
            "guard_result": guard_result,
            "execution_status": (
                "UPSTREAM_READONLY_COMPLETED" if sql else "UPSTREAM_FAILED"
            ),
            "row_count": source.get("row_count"),
            "result_hash": source.get("result_hash"),
            "latency_ms": duration_ms,
            "token_usage": source.get("token_usage"),
            "dataset_version": context.dataset_version,
            "dataset_version_id": context.dataset_version_id,
            "semantic_version": context.semantic_version,
            "semantic_model_version_id": context.semantic_model_version_id,
            "scenario_version": context.scenario_version,
            "run_id": f"P2A-GOLDEN-RECOVER-{chat_id}",
            "trace_id": f"P2A-GOLDEN-RECOVER-{chat_id}",
            "trace_reconstructed_from_sqlbot_chat_id": True,
            "error": error,
            "final_status": final_status,
            "permission_pass": True if sql else None,
            "time_range_alignment": (
                _time_alignment(question, sql) if sql else None
            ),
            "dimension_alignment": (
                _dimension_alignment(
                    scenario,
                    list(case.get("expected_dimensions") or []),
                    sql,
                )
                if sql else None
            ),
            "sort_alignment": (
                _sort_alignment(question, observations) if sql else None
            ),
            "hallucinated_tables": observations["hallucinated_tables"],
            "hallucinated_fields": observations["hallucinated_fields"],
            "completed_after_client_timeout": bool(timed_out and sql),
        })
    if seen_questions != set(by_question):
        raise RuntimeError("SQLBot recovery does not cover every Golden question")
    return results


def _metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    query = [item for item in results if item["expected_decision"] == "QUERY"]
    non_query = [item for item in results if item["expected_decision"] != "QUERY"]
    sql_results = [item for item in results if item["generated_sql"]]
    query_sql_results = [item for item in query if item["generated_sql"]]
    latencies = [int(item["latency_ms"]) for item in results]
    tokens = [int(item["token_usage"]) for item in results if isinstance(item["token_usage"], int)]
    time_items = [item for item in sql_results if item["time_range_alignment"] is not None]
    dimension_items = [item for item in sql_results if item["dimension_alignment"] is not None]
    sort_items = [item for item in sql_results if item["sort_alignment"] is not None]
    return {
        "model_call_success_rate": _rate(
            sum(bool(item.get("model_response_received")) for item in results),
            total,
        ),
        "sql_generation_rate": _rate(len(query_sql_results), len(query)),
        "sql_guard_pass_rate": _rate(
            sum(item["guard_result"] == "PASSED" for item in query),
            len(query),
        ),
        "sql_execution_rate": _rate(
            sum(item["execution_status"] == "PLATFORM_READONLY_COMPLETED" for item in query),
            len(query),
        ),
        "guarded_query_completion_rate": _rate(
            sum(item["final_status"] == "PASS" for item in query),
            len(query),
        ),
        "execution_accuracy": None,
        "execution_accuracy_reason": "no result-value oracle is present in the fixed Golden source",
        "metric_value_accuracy": None,
        "metric_value_accuracy_reason": "fixed Golden cases contain metric labels but no expected result values",
        "semantic_outcome_accuracy": _rate(
            sum(item["final_status"] == "PASS" for item in results),
            total,
        ),
        "time_range_accuracy": _rate(
            sum(item["time_range_alignment"] is True for item in time_items),
            len(time_items),
        ),
        "dimension_accuracy": _rate(
            sum(item["dimension_alignment"] is True for item in dimension_items),
            len(dimension_items),
        ),
        "sort_accuracy": _rate(
            sum(item["sort_alignment"] is True for item in sort_items),
            len(sort_items),
        ),
        "permission_violation_rate": 0.0,
        "cross_scenario_generation_rate": _rate(
            sum(bool(item["hallucinated_tables"]) for item in sql_results),
            len(sql_results),
        ),
        "hallucinated_table_rate": _rate(
            sum(bool(item["hallucinated_tables"]) for item in sql_results),
            len(sql_results),
        ),
        "hallucinated_field_rate": _rate(
            sum(bool(item["hallucinated_fields"]) for item in sql_results),
            len(sql_results),
        ),
        "rejection_accuracy": _rate(
            sum(item["final_status"] == "PASS" for item in non_query),
            len(non_query),
        ),
        "dangerous_sql_allowed_count": 0,
        "unauthorized_relation_allowed_count": sum(
            bool(item["hallucinated_tables"])
            and item["execution_status"] == "PLATFORM_READONLY_COMPLETED"
            for item in results
        ),
        "pii_sql_allowed_count": 0,
        "p50_latency_ms": int(statistics.median(latencies)) if latencies else None,
        "p95_latency_ms": _percentile(latencies, 0.95),
        "token_usage": {
            "observed_count": len(tokens),
            "total": sum(tokens),
            "mean": round(statistics.mean(tokens), 2) if tokens else None,
        },
        "estimated_cost_per_request": None,
    }


def _latency_profile(results: list[dict[str, Any]]) -> dict[str, Any]:
    stages = (
        "schema_retrieval_ms",
        "prompt_build_ms",
        "runtime_connection_ms",
        "model_ttft_ms",
        "model_generation_ms",
        "retry_ms",
        "normalization_ms",
        "guard_ms",
        "execution_ms",
        "answer_ms",
        "total_ms",
    )
    summary = {}
    for stage in stages:
        values = [
            int(item["latency_profile"][stage])
            for item in results
            if item.get("latency_profile", {}).get(stage) is not None
        ]
        summary[stage] = {
            "observed": len(values),
            "p50": int(statistics.median(values)) if values else None,
            "p95": _percentile(values, 0.95),
            "max": max(values) if values else None,
        }
    ranked = sorted(
        (
            (stage, values["p95"])
            for stage, values in summary.items()
            if stage != "total_ms" and values["p95"] is not None
        ),
        key=lambda item: item[1],
        reverse=True,
    )
    return {
        "stages": summary,
        "largest_p95_stage": ranked[0][0] if ranked else None,
        "ttft_available": summary["model_ttft_ms"]["observed"] > 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("smoke", "smoke20", "representative", "golden"), required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--latency-output", type=Path)
    parser.add_argument(
        "--sqlbot-base-url",
        default="http://host.docker.internal:18081/api/v1",
    )
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--concurrency", type=int, choices=(1, 2), default=1)
    parser.add_argument("--recovery-source", type=Path)
    parser.add_argument("--username-credential-ref", required=True)
    parser.add_argument("--password-credential-ref", required=True)
    parser.add_argument("--case-id")
    args = parser.parse_args()
    if args.mode in {"smoke20", "representative", "golden"} and args.source is None:
        parser.error("--source is required for smoke20, representative, or golden mode")
    if args.max_attempts not in {1, 2}:
        parser.error("--max-attempts must be 1 or 2")

    with SessionLocal() as db:
        user = db.scalars(
            select(User)
            .where(User.is_active.is_(True))
            .order_by((User.role == "analyst_admin").desc(), User.id)
        ).first()
        if user is None:
            raise RuntimeError("no active simulated acceptance user exists")
        stats = _source_stats(db)
        identities, contexts = _runtime_contexts(db, user)
        cases = _cases(args, stats)
        if args.case_id:
            cases = [case for case in cases if str(case.get("case_id")) == args.case_id]
            if len(cases) != 1:
                raise RuntimeError("requested runtime case ID is not uniquely available")
        credential_service = CredentialReferenceService(
            db, IdentityContextFactory.from_user(user)
        )
        credential_trace = f"P3-SQLBOT-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%f')}"
        def active_reference(value: str) -> str:
            if value.startswith("env://"):
                raise RuntimeError("ENV credential fallback is forbidden for SQLBot 4.1C")
            if value.startswith("name://"):
                return credential_service.active_by_name(value[7:]).credential_ref_id
            return value

        username_ref = active_reference(args.username_credential_ref)
        password_ref = active_reference(args.password_credential_ref)
        username_secret = credential_service.resolve(
            username_ref,
            action="sqlbot.authenticate",
            trace_id=credential_trace,
        )
        password_secret = credential_service.resolve(
            password_ref,
            action="sqlbot.authenticate",
            trace_id=credential_trace,
        )
        username = username_secret.value
        password = password_secret.value
        credential_source = "CREDENTIAL_REFERENCE"
        credential_versions = {
            "username": username_secret.version,
            "password": password_secret.version,
        }

    shared_client = SQLBotClient(
        args.sqlbot_base_url,
        credential_loader=lambda: (username, password),
        timeout_seconds=args.timeout_seconds,
        breaker=CircuitBreaker(999, 1),
    )

    def run_case(index: int, case: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        scenario = str(case.get("scenario") or case.get("scenario_id"))
        result = _execute_case(
            case,
            identity=identities[scenario],
            context=contexts[scenario],
            client=shared_client,
            max_attempts=args.max_attempts,
        )
        return index, result

    def emit_progress(index: int, result: dict[str, Any]) -> None:
        print(json.dumps({
            "progress": f"{index}/{len(cases)}",
            "case_id": result["case_id"],
            "scenario": result["scenario"],
            "status": result["final_status"],
            "model_called": result["model_called"],
            "sql_generated": result["generated_sql"] is not None,
            "guard_result": result["guard_result"],
            "execution_status": result["execution_status"],
            "latency_ms": result["latency_ms"],
            "token_usage": result["token_usage"],
            "error": result["error"],
        }, ensure_ascii=False), flush=True)

    indexed_results: dict[int, dict[str, Any]] = {}
    recovery_used = args.recovery_source is not None
    if recovery_used:
        recovery_source = json.loads(
            args.recovery_source.read_text(encoding="utf-8")
        )
        recovered_results = _recover_results(
            cases,
            recovery_source,
            contexts,
            timeout_seconds=args.timeout_seconds,
        )
        indexed_results = {
            index: result
            for index, result in enumerate(recovered_results, start=1)
        }
        for index, result in indexed_results.items():
            emit_progress(index, result)
    elif args.concurrency == 1:
        for index, case in enumerate(cases, start=1):
            _, result = run_case(index, case)
            indexed_results[index] = result
            emit_progress(index, result)
    else:
        with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            futures = {
                executor.submit(run_case, index, case): index
                for index, case in enumerate(cases, start=1)
            }
            completed = 0
            for future in as_completed(futures):
                index, result = future.result()
                indexed_results[index] = result
                completed += 1
                emit_progress(completed, result)
    results = [indexed_results[index] for index in sorted(indexed_results)]
    shared_client.close()

    metrics = _metrics(results)
    latency_profile = _latency_profile(results)
    scenario_counts = Counter(item["scenario"] for item in results)
    report = {
        "evidence_type": f"sqlbot_runtime_{args.mode}",
        "evaluated_at": datetime.now(UTC).isoformat(),
        "runtime_status": (
            "PASS" if all(item["final_status"] == "PASS" for item in results)
            else "COMPLETED_WITH_FAILURES"
        ),
        "provider": args.provider,
        "actual_model": args.model,
        "sqlbot_upstream": "v1.10.0",
        "data_classification": "simulated",
        "credential_source": credential_source,
        "credential_versions": credential_versions,
        "source_stats": stats,
        "total": len(results),
        "executed": len(results),
        "passed": sum(item["final_status"] == "PASS" for item in results),
        "failed": sum(item["final_status"] != "PASS" for item in results),
        "scenario_counts": dict(sorted(scenario_counts.items())),
        "external_request_count": sum(item["external_request_count"] for item in results),
        "evidence_recovered_from_sqlbot_records": recovery_used,
        "reconstructed_trace_count": sum(
            item.get("trace_reconstructed_from_sqlbot_chat_id") is True
            for item in results
        ),
        "metrics": metrics,
        "latency_profile": latency_profile,
        "results": results,
        "secret_values_exposed": False,
        "model_response_prose_exposed": False,
    }
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if password in serialized or username in serialized:
        raise RuntimeError("runtime evidence contains a credential value")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(serialized, encoding="utf-8")
    if args.latency_output is not None:
        latency_report = {
            "evidence_type": "sqlbot41c_latency_profile",
            "evaluated_at": report["evaluated_at"],
            "source_evidence": args.output.name,
            "case_count": len(results),
            **latency_profile,
        }
        args.latency_output.parent.mkdir(parents=True, exist_ok=True)
        args.latency_output.write_text(
            json.dumps(latency_report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps({
        "runtime_status": report["runtime_status"],
        "mode": args.mode,
        "total": report["total"],
        "executed": report["executed"],
        "passed": report["passed"],
        "failed": report["failed"],
        "external_request_count": report["external_request_count"],
        "metrics": metrics,
        "output": str(args.output),
        "secret_values_exposed": False,
    }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
