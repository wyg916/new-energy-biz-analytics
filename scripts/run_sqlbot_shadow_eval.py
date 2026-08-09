"""Run a bounded real SQLBot Shadow evaluation for both active scenarios.

The deterministic engine remains the returned main path. SQLBot executes in the
background through the production EngineRouter and RoutingEvidenceRepository.
The JSON artifact contains SQL and hashes, but no result rows, credentials,
session tokens, or model prose.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, text

from app.chatbi.engine import DeterministicEngine
from app.chatbi.service import ChatBIService
from app.core.database import SessionLocal
from app.models.auth import User
from app.models.query_routing import QueryRouteDecisionRecord, ShadowEvaluation
from app.platform.query_engine import QueryRequest
from app.query_engines.context import build_query_context
from app.query_engines.router import EngineMode, EngineRouter
from app.query_engines.shadow import RoutingEvidenceRepository
from app.query_engines.sqlbot.client import SQLBotClient
from app.query_engines.sqlbot.engine import SQLBotEngine
from app.query_engines.sqlbot.health import CircuitBreaker
from app.query_engines.sqlbot.readonly_executor import execute_generated_readonly
from app.query_engines.sqlbot.session_manager import SQLBotSessionManager
from app.scenarios.charging_ops.runtime import resolve_charging_ops_context
from app.scenarios.sales_ops.engine import SalesOpsDeterministicEngine
from app.scenarios.sales_ops.runtime import resolve_sales_ops_context
from app.governance.secrets import CredentialReferenceService
from app.platform.identity import IdentityContextFactory


DATASOURCE_IDS = {"charging_ops": "1", "sales_ops": "2"}


def _sha256(value: str | None) -> str | None:
    return hashlib.sha256(value.encode()).hexdigest() if value else None


def _source_stats(db) -> dict[str, dict[str, Any]]:
    charging = db.execute(text("""
        SELECT
          MIN((start_time AT TIME ZONE 'Asia/Shanghai')::date),
          MAX((start_time AT TIME ZONE 'Asia/Shanghai')::date),
          COUNT(*)
        FROM fact_charging_session
    """)).one()
    sales = db.execute(text("""
        SELECT MIN(order_date), MAX(order_date), COUNT(*) FROM sales_order
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


def _cases(path: Path) -> list[dict[str, Any]]:
    source = json.loads(path.read_text(encoding="utf-8"))
    selected: list[dict[str, Any]] = []
    for category in (
        "single_metric",
        "filter_sort",
        "trend_comparison",
        "multi_table_dimension",
        "ambiguity_security_refusal",
    ):
        for scenario in ("charging_ops", "sales_ops"):
            matching = [
                case
                for case in source.get("cases", [])
                if case.get("scenario_id") == scenario
                and case.get("category") == category
            ][:5]
            if len(matching) != 5:
                raise RuntimeError("real Shadow requires five cases per category/scenario")
            selected.extend(matching)
    return selected


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--sqlbot-base-url", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--username-credential-ref", required=True)
    parser.add_argument("--password-credential-ref", required=True)
    args = parser.parse_args()

    cases = _cases(args.source)
    evaluated_at = datetime.now(UTC)
    results: list[dict[str, Any]] = []

    with SessionLocal() as db:
        user = db.scalar(
            select(User)
            .where(User.is_active.is_(True))
            .order_by((User.role == "analyst_admin").desc(), User.id)
        )
        if user is None:
            raise RuntimeError("no active acceptance user")

        credential_service = CredentialReferenceService(
            db, IdentityContextFactory.from_user(user)
        )
        credential_trace = f"P3-SQLBOT-SHADOW-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%f')}"
        def active_reference(value: str) -> str:
            if value.startswith("env://"):
                raise RuntimeError("ENV credential fallback is forbidden for SQLBot 4.1C")
            if value.startswith("name://"):
                return credential_service.active_by_name(value[7:]).credential_ref_id
            return value

        username = credential_service.resolve(
            active_reference(args.username_credential_ref),
            action="sqlbot.authenticate",
            trace_id=credential_trace,
        ).value
        password = credential_service.resolve(
            active_reference(args.password_credential_ref),
            action="sqlbot.authenticate",
            trace_id=credential_trace,
        ).value

        charging_identity, charging_active = resolve_charging_ops_context(db, user)
        sales_identity, sales_active = resolve_sales_ops_context(db, user)
        identities = {
            "charging_ops": charging_identity,
            "sales_ops": sales_identity,
        }
        active_contexts = {
            "charging_ops": charging_active,
            "sales_ops": sales_active,
        }
        repository = RoutingEvidenceRepository(db)
        client = SQLBotClient(
            args.sqlbot_base_url,
            credential_loader=lambda: (username, password),
            timeout_seconds=args.timeout_seconds,
            breaker=CircuitBreaker(100, recovery_seconds=1),
        )
        sqlbot = SQLBotEngine(
            enabled=True,
            runtime_verified=True,
            client=client,
            session_manager=SQLBotSessionManager(
                on_bind=repository.record_session_binding
            ),
            generated_sql_executor=execute_generated_readonly,
        )

        try:
            for index, case in enumerate(cases, 1):
                scenario = str(case["scenario_id"])
                trace_id = (
                    f"P2A-SHADOW-{case['case_id']}-"
                    f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%f')}"
                )
                identity = replace(identities[scenario], request_id=trace_id)
                conversation_id = f"p2a-shadow-{scenario}-{case['case_id'].lower()}"
                context = replace(
                    build_query_context(
                        db,
                        conversation_id=conversation_id,
                        platform_context=active_contexts[scenario],
                    ),
                    datasource_id=DATASOURCE_IDS[scenario],
                    max_rows=500,
                )
                request = QueryRequest(
                    question=str(case["question"]),
                    identity_context=identity,
                    scenario_id=scenario,
                )
                if scenario == "charging_ops":
                    service = ChatBIService(db, user, conversation_id=conversation_id)
                    service.platform_context = active_contexts[scenario]
                    deterministic = DeterministicEngine(
                        service._ask_deterministic,
                        active_contexts[scenario],
                    )
                else:
                    deterministic = SalesOpsDeterministicEngine(db)

                routed = EngineRouter(
                    deterministic,
                    sqlbot,
                    mode=EngineMode.SHADOW,
                    evidence=repository,
                    feature_flag_version="p2a-runtime-closeout",
                ).execute(request, context, deterministic_supported=True)
                shadow = db.scalar(
                    select(ShadowEvaluation).where(
                        ShadowEvaluation.trace_id == trace_id
                    )
                )
                route = db.scalar(
                    select(QueryRouteDecisionRecord).where(
                        QueryRouteDecisionRecord.trace_id == trace_id
                    )
                )
                if shadow is None or route is None:
                    raise RuntimeError(f"shadow evidence was not persisted for {case['case_id']}")

                item = {
                    "case_id": case["case_id"],
                    "scenario": scenario,
                    "question": case["question"],
                    "main_engine": routed.result.engine,
                    "main_status": routed.result.status,
                    "main_result_hash": shadow.deterministic_result_hash,
                    "route_decision": route.route_decision,
                    "route_reason": route.route_reason,
                    "sqlbot_generated_sql": shadow.sqlbot_sql,
                    "sqlbot_sql_hash": _sha256(shadow.sqlbot_sql),
                    "sqlbot_result_hash": shadow.sqlbot_result_hash,
                    "sqlbot_row_count": shadow.row_count,
                    "sqlbot_latency_ms": shadow.latency_ms,
                    "sqlbot_token_usage": shadow.token_usage,
                    "permission_result": shadow.permission_result,
                    "execution_accuracy": shadow.execution_accuracy,
                    "metric_value_match": shadow.metric_value_match,
                    "error_code": shadow.error_code,
                    "run_id": shadow.run_id,
                    "trace_id": shadow.trace_id,
                    "shadow_evaluation_id": shadow.shadow_evaluation_id,
                    "route_decision_id": route.route_decision_id,
                }
                results.append(item)
                print(json.dumps({
                    "progress": f"{index}/50",
                    "case_id": case["case_id"],
                    "scenario": scenario,
                    "main_status": routed.result.status,
                    "shadow_sql": shadow.sqlbot_sql is not None,
                    "token_observed": shadow.token_usage is not None,
                    "error_code": shadow.error_code,
                }, ensure_ascii=False), flush=True)
        finally:
            client.close()

        source_stats = _source_stats(db)

    completed = [item for item in results if item["sqlbot_generated_sql"]]
    latencies = sorted(
        int(item["sqlbot_latency_ms"])
        for item in results
        if item["sqlbot_latency_ms"] is not None
    )
    report = {
        "evidence_type": "sqlbot_real_shadow_50",
        "evaluated_at": evaluated_at.isoformat(),
        "runtime_status": "COMPLETED_WITH_FAILURES"
        if len(completed) < len(results)
        else "COMPLETED",
        "provider": args.provider,
        "actual_model": args.model,
        "sqlbot_upstream": "v1.10.0",
        "data_classification": "simulated",
        "source_stats": source_stats,
        "total": len(results),
        "scenario_counts": {
            scenario: sum(item["scenario"] == scenario for item in results)
            for scenario in ("charging_ops", "sales_ops")
        },
        "main_deterministic_success_count": sum(
            item["main_engine"] == "deterministic"
            and item["main_status"] in {"completed", "succeeded"}
            for item in results
        ),
        "real_sqlbot_shadow_request_count": len(results),
        "sql_generated_count": len(completed),
        "token_observed_count": sum(
            isinstance(item["sqlbot_token_usage"], int) for item in results
        ),
        "guard_pass_count": sum(
            item["permission_result"] == "PASS" for item in results
        ),
        "exact_result_match_count": sum(
            item["execution_accuracy"] == 1.0 for item in results
        ),
        "semantic_correct_count": sum(
            item["metric_value_match"] is True for item in results
        ),
        "p95_latency_ms": latencies[max(0, math.ceil(len(latencies) * 0.95) - 1)]
        if latencies else None,
        "results": results,
        "secret_values_exposed": False,
        "model_response_prose_exposed": False,
    }
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if password in serialized or username in serialized:
        raise RuntimeError("shadow evidence contains a credential value")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(serialized, encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "total": report["total"],
        "main_success": report["main_deterministic_success_count"],
        "sql_generated": report["sql_generated_count"],
        "token_observed": report["token_observed_count"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
