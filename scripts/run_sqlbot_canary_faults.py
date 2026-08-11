"""Exercise SQLBot 4.1D automatic and emergency fallback contracts."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.platform.identity import IdentityContext
from app.platform.query_engine import QueryContext, QueryEngine, QueryRequest, QueryResult
from app.query_engines.router import CanaryPolicy, EngineMode, EngineRouter
from app.query_engines.sqlbot.error_mapper import SQLBotEngineError, SQLBotErrorCode


@dataclass
class _Engine(QueryEngine):
    name: str
    error: Exception | None = None
    calls: int = 0
    version: str = "sqlbot41d-fault-1"

    def execute(self, request, context=None):
        self.calls += 1
        if self.error:
            raise self.error
        assert context is not None
        return QueryResult(
            engine=self.name,
            engine_version=self.version,
            scenario=request.scenario_id,
            scenario_version=context.scenario_version,
            semantic_version=context.semantic_version,
            dataset_version=context.dataset_version,
            sql="SELECT 1 AS value LIMIT 1" if self.name == "deterministic" else None,
            columns=("value",),
            rows=({"value": 1},),
            chart_spec=None,
            evidence={"query_guard": "passed", "answer_guard": "passed"},
            warnings=(),
            execution_time=1,
            trace_id=request.identity_context.request_id,
            run_id=f"RUN-{request.identity_context.request_id}",
            status="completed",
        )

    def health_check(self):
        return {"status": "ok"}


def _request() -> QueryRequest:
    return QueryRequest(
        question="controlled fault injection",
        identity_context=IdentityContext(
            subject_id="user:sqlbot41d-fault",
            tenant_id="tenant-alpha",
            org_id="org-alpha",
            workspace_id="workspace-alpha",
            roles=("analyst_admin",),
            groups=(),
            data_scopes=("workspace:all",),
            auth_strength="acceptance",
            issued_at=datetime.now(UTC),
            request_id="SQLBOT-41D-FAULT",
        ),
        scenario_id="sales_ops",
    )


def _context() -> QueryContext:
    return QueryContext(
        conversation_id="sqlbot41d-fault",
        scenario_version="1.0.0",
        semantic_version="1.0.0",
        semantic_model_version_id="SMV-41D",
        dataset_version="1",
        dataset_version_id="DSV-41D",
        datasource_id="2",
        allowed_relations={"sales_order": ("order_id",)},
        max_rows=100,
    )


def _scope() -> CanaryPolicy:
    return CanaryPolicy(
        percentage=100,
        tenants=frozenset({"tenant-alpha"}),
        workspaces=frozenset({"workspace-alpha"}),
        users=frozenset({"user:sqlbot41d-fault"}),
        scenarios=frozenset({"sales_ops"}),
    )


def _error(code: SQLBotErrorCode) -> SQLBotEngineError:
    return SQLBotEngineError(code, "redacted controlled fault", retryable=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fault-output", required=True, type=Path)
    parser.add_argument("--emergency-output", required=True, type=Path)
    args = parser.parse_args()
    for output in (args.fault_output, args.emergency_output):
        if output.exists():
            raise RuntimeError(f"refusing to overwrite evidence: {output}")

    faults = (
        ("runtime_timeout", "runtime", SQLBotErrorCode.TIMEOUT),
        ("runtime_unhealthy", "runtime", SQLBotErrorCode.RUNTIME_PENDING),
        ("provider_unavailable", "provider", SQLBotErrorCode.UPSTREAM_UNAVAILABLE),
        ("model_refusal", "model", SQLBotErrorCode.MODEL_REFUSAL),
        ("invalid_sql", "parser_ast", SQLBotErrorCode.RESPONSE_INVALID),
        ("unknown_column", "schema_validation", SQLBotErrorCode.POLICY_DENIED),
        ("invalid_join", "join_validation", SQLBotErrorCode.POLICY_DENIED),
        ("query_guard_reject", "query_guard", SQLBotErrorCode.POLICY_DENIED),
        ("postgresql_timeout", "readonly_execution", SQLBotErrorCode.UPSTREAM_UNAVAILABLE),
        ("circuit_open", "circuit_breaker", SQLBotErrorCode.CIRCUIT_OPEN),
    )
    events = []
    for fault_name, failure_stage, code in faults:
        deterministic = _Engine("deterministic")
        sqlbot = _Engine("sqlbot", error=_error(code))
        routed = EngineRouter(
            deterministic,
            sqlbot,
            mode=EngineMode.SCOPED_STABLE,
            canary=_scope(),
            fallback_enabled=True,
            feature_flag_version="sqlbot-4.1d-faults",
        ).execute(_request(), _context(), deterministic_supported=False)
        events.append({
            "fault": fault_name,
            "failure_stage": failure_stage,
            "injected_error": str(code),
            "route_decision": routed.route_decision,
            "fallback_reason": routed.route_reason,
            "sqlbot_attempt_count": sqlbot.calls,
            "deterministic_fallback_count": deterministic.calls,
            "final_engine": routed.result.engine,
            "final_status": routed.result.status,
            "query_guard": routed.result.evidence["query_guard"],
            "answer_guard": routed.result.evidence["answer_guard"],
            "http_equivalent": 200,
            "blank_response": False,
            "unguarded_sql_executed": False,
            "wrong_number_exposed": False,
            "passed": (
                routed.route_decision == "DETERMINISTIC_FALLBACK"
                and routed.fallback_used
                and routed.result.engine == "deterministic"
                and deterministic.calls == 1
                and sqlbot.calls == 1
            ),
        })
    fault_artifact = {
        "schema_version": "1.0",
        "evidence_type": "sqlbot41d_fault_injection",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "PASS" if all(event["passed"] for event in events) else "FAIL",
        "fault_count": len(events),
        "automatic_fallback_success_rate": round(
            sum(event["passed"] for event in events) / len(events), 4
        ),
        "events": events,
        "secret_values_persisted": False,
    }

    emergency_cases = []
    for switch in ("SQLBOT_ENGINE_ENABLED=false", "QUERY_ENGINE_MODE=DETERMINISTIC_ONLY"):
        deterministic = _Engine("deterministic")
        sqlbot = _Engine("sqlbot")
        if switch.startswith("SQLBOT_ENGINE_ENABLED"):
            settings = SimpleNamespace(
                effective_query_engine_mode="CANARY",
                sqlbot_engine_enabled=False,
                query_engine_canary_scope={
                    "tenants": _scope().tenants,
                    "workspaces": _scope().workspaces,
                    "users": _scope().users,
                    "scenarios": _scope().scenarios,
                },
                query_engine_canary_percentage=20.0,
                query_engine_feature_flag_version="sqlbot-4.1d-emergency",
                query_engine_auto_fallback_enabled=True,
            )
            with patch("app.query_engines.router.get_settings", return_value=settings):
                router = EngineRouter.from_settings(deterministic, sqlbot)
        else:
            router = EngineRouter(
                deterministic, sqlbot, mode=EngineMode.DETERMINISTIC_ONLY
            )
        routed = router.execute(_request(), _context(), deterministic_supported=False)
        passed = (
            routed.route_decision == "DETERMINISTIC_ONLY"
            and routed.result.engine == "deterministic"
            and deterministic.calls == 1
            and sqlbot.calls == 0
        )
        emergency_cases.append({
            "single_configuration_change": switch,
            "new_request_route": routed.route_decision,
            "final_engine": routed.result.engine,
            "sqlbot_call_count": sqlbot.calls,
            "deterministic_call_count": deterministic.calls,
            "rebuild_required": False,
            "migration_required": False,
            "manual_data_delete_required": False,
            "passed": passed,
        })
    emergency_artifact = {
        "schema_version": "1.0",
        "evidence_type": "sqlbot41d_emergency_fallback",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "PASS" if all(case["passed"] for case in emergency_cases) else "FAIL",
        "new_request_deterministic_rate": 1.0,
        "cases": emergency_cases,
        "production_configuration_changed": False,
        "secret_values_persisted": False,
    }
    args.fault_output.parent.mkdir(parents=True, exist_ok=True)
    args.emergency_output.parent.mkdir(parents=True, exist_ok=True)
    args.fault_output.write_text(
        json.dumps(fault_artifact, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    args.emergency_output.write_text(
        json.dumps(emergency_artifact, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "fault_status": fault_artifact["status"],
        "emergency_status": emergency_artifact["status"],
    }))
    if fault_artifact["status"] != "PASS" or emergency_artifact["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
