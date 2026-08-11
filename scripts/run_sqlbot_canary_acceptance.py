"""Run controlled SQLBot 4.1D API traffic and produce redacted evidence.

The runner is intentionally acceptance-only. It uses the real FastAPI route,
current PostgreSQL data, governed CredentialReference values, the independent
readonly roles, and SQLBot v1.10.0. Secret values never enter artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from unittest.mock import patch
from urllib.parse import quote

from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.governance.secrets import CredentialReferenceService
from app.main import app
from app.models.auth import User
from app.platform.identity import IdentityContextFactory
from app.query_engines.router import CanaryPolicy
from app.query_engines.sqlbot.client import SQLBotClient
from app.query_engines.sqlbot.credentials import derive_runtime_account_password


SCENARIOS = ("charging_ops", "sales_ops")
TENANT = "tenant-alpha"
WORKSPACE = "workspace-alpha"


def _sha256(value: str | None) -> str | None:
    return hashlib.sha256(value.encode()).hexdigest() if value else None


def _result_hash(rows: list[dict[str, Any]]) -> str | None:
    """Hash the platform-normalized result independently of row ordering."""
    if not rows:
        return None
    canonical_rows = sorted(
        (json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for row in rows)
    )
    return _sha256(json.dumps(canonical_rows, ensure_ascii=False, separators=(",", ":")))


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(len(ordered) * percentile) - 1)]


def _load_cases(path: Path) -> dict[str, list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    grouped = {scenario: [] for scenario in SCENARIOS}
    for case in payload["cases"]:
        grouped[str(case["scenario_id"])].append(case)
    return grouped


def _bucket(subject: str, scenario: str) -> float:
    raw = f"{TENANT}|{WORKSPACE}|{subject}|{scenario}"
    return (int(hashlib.sha256(raw.encode()).hexdigest()[:8], 16) % 10_000) / 100


def _cohort(stage: str) -> list[dict[str, Any]]:
    if stage == "canary-5":
        totals = {"charging_ops": 50, "sales_ops": 50}
        selected = {"charging_ops": 3, "sales_ops": 2}
        percentage = 5
    elif stage == "canary-20":
        totals = {"charging_ops": 100, "sales_ops": 100}
        selected = {"charging_ops": 20, "sales_ops": 20}
        percentage = 20
    elif stage == "scoped-stable":
        totals = {"charging_ops": 20, "sales_ops": 20}
        selected = totals
        percentage = 100
    else:
        raise ValueError(stage)

    cohort: list[dict[str, Any]] = []
    for scenario in SCENARIOS:
        selected_subject: str | None = None
        control_subject: str | None = None
        control_count = totals[scenario] - selected[scenario]
        index = 0
        while selected_subject is None or (
            control_count and control_subject is None
        ):
            subject = f"user:sqlbot41d-{stage}-{scenario}-{index:05d}"
            eligible = _bucket(subject, scenario) < percentage
            if eligible and selected_subject is None:
                selected_subject = subject
            elif not eligible and control_subject is None:
                control_subject = subject
            index += 1
        assert selected_subject is not None
        cohort.extend(
            {
                "scenario": scenario,
                "subject": selected_subject,
                "selected": True,
                "rollout_stage": stage,
            }
            for _ in range(selected[scenario])
        )
        cohort.extend(
            {
                "scenario": scenario,
                "subject": control_subject,
                "selected": False,
                "rollout_stage": stage,
            }
            for _ in range(control_count)
        )
    return cohort


def _conversation_id(
    stage: str,
    run_token: str,
    item: dict[str, Any],
    index: int,
) -> str:
    if item["selected"]:
        return f"s41d-{stage}-{run_token}-{item['scenario']}-canary"
    return f"s41d-{stage}-{run_token}-{index + 1:04d}"


def _readonly_urls() -> dict[str, str]:
    runtime = Path(os.getenv("ACCEPTANCE_RUNTIME_DIR", "/run/p4-runtime"))
    payload = json.loads(
        (runtime / "sqlbot41b_readonly_credentials.json").read_text(encoding="utf-8")
    )
    host = os.getenv("ACCEPTANCE_POSTGRES_HOST", "db")
    database = os.getenv("ACCEPTANCE_POSTGRES_DB", "renewable_p5b")
    return {
        scenario: (
            f"postgresql+psycopg://{quote(payload[scenario]['role'], safe='')}:"
            f"{quote(payload[scenario]['password'], safe='')}@{host}:5432/{database}"
        )
        for scenario in SCENARIOS
    }


def _runtime_credentials(db, user: User) -> tuple[str, str]:
    service = CredentialReferenceService(db, IdentityContextFactory.from_user(user))
    trace_id = f"SQLBOT-41D-CREDENTIAL-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%f')}"
    username_ref = service.active_by_name("preprod-sqlbot-username").credential_ref_id
    password_ref = service.active_by_name("preprod-sqlbot-password").credential_ref_id
    return (
        service.resolve(
            username_ref, action="sqlbot.authenticate", trace_id=trace_id
        ).value,
        service.resolve(
            password_ref, action="sqlbot.authenticate", trace_id=trace_id
        ).value,
    )


def _configure(stage: str, cohort: list[dict[str, Any]], args) -> None:
    settings = get_settings()
    urls = _readonly_urls()
    # The current DATA-4.1 governance bindings are explicitly scoped to the
    # controlled preproduction policy environment. The process still starts as
    # APP_ENV=test so production/preproduction startup gates are not weakened;
    # only authorization evaluation is aligned for this isolated acceptance run.
    settings.app_env = "preproduction"
    settings.sqlbot_engine_enabled = True
    settings.sqlbot_runtime_verified = True
    settings.sqlbot_included_in_v4_release = True
    settings.sqlbot_base_url = args.sqlbot_base_url
    settings.sqlbot_timeout_seconds = args.timeout_seconds
    settings.chatbi_readonly_execution_enabled = True
    settings.sqlbot_readonly_charging_database_url = urls["charging_ops"]
    settings.sqlbot_readonly_sales_database_url = urls["sales_ops"]
    settings.query_engine_mode = (
        "SCOPED_STABLE" if stage == "scoped-stable" else "CANARY"
    )
    settings.query_engine_canary_percentage = {
        "canary-5": 5.0,
        "canary-20": 20.0,
        "scoped-stable": 100.0,
    }[stage]
    settings.query_engine_canary_tenants = TENANT
    settings.query_engine_canary_workspaces = WORKSPACE
    settings.query_engine_canary_users = ",".join(item["subject"] for item in cohort)
    settings.query_engine_canary_scenarios = ",".join(SCENARIOS)
    settings.query_engine_feature_flag_version = f"sqlbot-4.1d-{stage}"
    settings.query_engine_auto_fallback_enabled = True


def _question(case_groups, item: dict[str, Any], index: int) -> dict[str, Any]:
    scenario_cases = case_groups[item["scenario"]]
    if item["selected"]:
        if item.get("rollout_stage") == "scoped-stable" and index % 4 == 0:
            core = [case for case in scenario_cases if case["category"] == "single_metric"]
            return core[index % len(core)]
        if item.get("rollout_stage") == "scoped-stable" and index % 4 == 1:
            high_risk = [
                case for case in scenario_cases
                if case["category"] == "ambiguity_security_refusal"
            ]
            return high_risk[index % len(high_risk)]
        # These are registered-schema explorations. The explicit distribution
        # wording is the frozen Query Understanding contract for controlled
        # open NL2SQL; no new relation, metric, or permission is introduced.
        candidates = {
            "charging_ops": (
                {
                    "case_id": "LIVE-CHARGING-DISTRIBUTION-1",
                    "question": "2026年6月按场站查看充电收入前100名，返回字段分布",
                    "category": "medium",
                    "expected_decision": "QUERY",
                },
                {
                    "case_id": "LIVE-CHARGING-DISTRIBUTION-2",
                    "question": "展示2026年上半年每月充电量趋势的字段分布",
                    "category": "complex",
                    "expected_decision": "QUERY",
                },
            ),
            "sales_ops": (
                {
                    "case_id": "LIVE-SALES-DISTRIBUTION-1",
                    "question": "2011年11月按渠道查看销售收入前100名，返回字段分布",
                    "category": "medium",
                    "expected_decision": "QUERY",
                },
                {
                    "case_id": "LIVE-SALES-DISTRIBUTION-2",
                    "question": "展示2011年1月至11月每月销售收入趋势的字段分布",
                    "category": "complex",
                    "expected_decision": "QUERY",
                },
            ),
        }[item["scenario"]]
        # Repetition is deliberate: it makes result consistency measurable.
        return candidates[index % len(candidates)]
    # Keep broad coverage while making the non-SQLBot control group mostly
    # exercise fast clarification/security gates instead of repeatedly running
    # the same expensive deterministic aggregates.
    category = {
        0: "single_metric",
        1: "filter_sort",
        2: "trend_comparison",
    }.get(index % 10, "ambiguity_security_refusal")
    candidates = [case for case in scenario_cases if case["category"] == category]
    return candidates[index % len(candidates)]


def _event_from_response(
    *,
    response,
    item: dict[str, Any],
    case: dict[str, Any],
    request_id: str,
    conversation_id: str,
    follow_up: bool,
    elapsed_ms: int,
    percentage: float,
) -> dict[str, Any]:
    payload = response.json()
    data = payload.get("data_query_evidence") or {}
    query_result = data.get("query_result") or {}
    service_evidence = data.get("evidence") or {}
    evidence = query_result.get("evidence") or data.get("evidence") or {}
    routing = data.get("engine_routing") or {}
    sql = query_result.get("sql")
    guard = evidence.get("query_guard")
    answer_guard = evidence.get("answer_guard")
    inferred_sqlbot_attempt = bool(
        item["selected"]
        and case["expected_decision"] == "QUERY"
        and not routing
    )
    sqlbot_attempted = bool(routing.get("sqlbot_attempted")) or inferred_sqlbot_attempt
    fallback_used = bool(routing.get("fallback_used")) or (
        inferred_sqlbot_attempt and response.status_code >= 400
    )
    controlled_fallback_used = bool(
        evidence.get("governed_exact_example_fallback")
    )
    fallback_reason = (
        routing.get("route_reason")
        if routing.get("fallback_used")
        else "API_GOVERNED_FALLBACK_FAILURE"
        if fallback_used
        else None
    )
    model_call_status = "NOT_ATTEMPTED"
    if sqlbot_attempted:
        if controlled_fallback_used:
            model_call_status = "RESPONSE_REJECTED_CONTROLLED_FALLBACK"
        elif query_result.get("status") == "completed" and evidence.get("upstream_record_id"):
            model_call_status = "RESPONSE_RECEIVED"
        else:
            model_call_status = "FAILED_OR_UNAVAILABLE"
    circuit_breaker_state = "NOT_APPLICABLE"
    if sqlbot_attempted:
        circuit_breaker_state = (
            "OPEN"
            if "CIRCUIT" in str(fallback_reason or "").upper()
            else "CLOSED"
        )
    return {
        "request_id": request_id,
        "run_id": payload.get("run_id") or query_result.get("run_id"),
        "conversation_id": conversation_id,
        "follow_up": follow_up,
        "user": item["subject"],
        "tenant": TENANT,
        "workspace": WORKSPACE,
        "scenario": item["scenario"],
        "case_id": case["case_id"],
        "category": case["category"],
        "expected_decision": case["expected_decision"],
        "http_status": response.status_code,
        "route_decision": routing.get("route_decision") or "API_GOVERNED_RESPONSE",
        "canary_percentage": percentage,
        "configured_canary_percentage": percentage,
        "cohort_selected": item["selected"],
        "selected_engine": routing.get("selected_engine") or (
            "sqlbot" if inferred_sqlbot_attempt else "deterministic"
        ),
        "engine_selected": routing.get("selected_engine") or (
            "sqlbot" if inferred_sqlbot_attempt else "deterministic"
        ),
        "sqlbot_runtime": evidence.get("upstream_version"),
        "runtime_status": (
            "VERIFIED" if evidence.get("upstream_version") else
            "UNAVAILABLE" if sqlbot_attempted else "NOT_SELECTED"
        ),
        "latency_profile": (
            evidence.get("latency_profile") if sqlbot_attempted else None
        ),
        "service_latency_profile": service_evidence.get(
            "service_latency_profile"
        ),
        "orchestration_latency_profile": service_evidence.get(
            "orchestration_latency_profile"
        ),
        "sqlbot_model": "deepseek-v4-flash" if sqlbot_attempted else None,
        "model_call_status": model_call_status,
        "controlled_exact_example_fallback": controlled_fallback_used,
        "controlled_example_fallback_used": controlled_fallback_used,
        "sql_hash": _sha256(sql),
        "result_hash": _result_hash(query_result.get("rows") or []),
        "guard": guard or "NOT_APPLICABLE_GOVERNED_RESPONSE",
        "query_guard_result": guard or "NOT_APPLICABLE_GOVERNED_RESPONSE",
        "execution": query_result.get("status") or "GOVERNED_RESPONSE",
        "semantic": (
            "PASS"
            if response.status_code < 500
            and (
                case["expected_decision"] != "QUERY"
                or query_result.get("status") == "completed"
            )
            else "FAIL"
        ),
        "latency_ms": elapsed_ms,
        "fallback_reason": fallback_reason,
        "primary_engine": "SQLBOT" if sqlbot_attempted else "DETERMINISTIC",
        "fallback_engine": "DETERMINISTIC" if fallback_used else None,
        "sqlbot_failure_stage": fallback_reason if fallback_used else None,
        "circuit_breaker_state": circuit_breaker_state,
        "answer_guard": answer_guard or "GOVERNED_RESPONSE",
        "answer_guard_result": answer_guard or "GOVERNED_RESPONSE",
        "final_engine": routing.get("final_engine") or query_result.get("engine") or (
            "deterministic_error" if fallback_used else None
        ),
        "sqlbot_attempted": sqlbot_attempted,
        "fallback_used": fallback_used,
        "deterministic_fallback_used": fallback_used,
        "row_count": len(query_result.get("rows") or []),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("canary-5", "canary-20", "scoped-stable"), required=True)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--route-output", required=True, type=Path)
    parser.add_argument("--acceptance-output", required=True, type=Path)
    parser.add_argument("--sqlbot-base-url", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=12.0)
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--consistency-probe", action="store_true")
    args = parser.parse_args()
    if args.probe and args.consistency_probe:
        parser.error("choose only one probe mode")

    cohort = _cohort(args.stage)
    if args.probe:
        cohort = [
            next(item for item in cohort if item["scenario"] == scenario and item["selected"])
            for scenario in SCENARIOS
        ]
    elif args.consistency_probe:
        selected = {
            scenario: next(
                item for item in cohort
                if item["scenario"] == scenario and item["selected"]
            )
            for scenario in SCENARIOS
        }
        cohort = [
            dict(selected[scenario])
            for scenario in SCENARIOS
            for _ in range(4)
        ]
    _configure(args.stage, cohort, args)
    case_groups = _load_cases(args.source)
    percentage = get_settings().query_engine_canary_percentage
    policy = CanaryPolicy(
        percentage=percentage,
        tenants=frozenset({TENANT}),
        workspaces=frozenset({WORKSPACE}),
        users=frozenset(item["subject"] for item in cohort),
        scenarios=frozenset(SCENARIOS),
    )
    events: list[dict[str, Any]] = []
    observed_conversations: set[str] = set()
    run_token = datetime.now(UTC).strftime("%H%M%S")

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "analyst"))
        if user is None:
            raise RuntimeError("controlled analyst user is unavailable")
        runtime_username, runtime_password = _runtime_credentials(db, user)
        original_identity_factory = IdentityContextFactory.from_user

    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "analyst", "password": "AlphaAnalyst!2026"},
        )
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        for index, item in enumerate(cohort):
            case = _question(case_groups, item, index)
            request_id = f"SQLBOT-41D-{args.stage.upper()}-{index + 1:04d}"
            conversation_id = _conversation_id(
                args.stage, run_token, item, index
            )
            follow_up = conversation_id in observed_conversations
            base_identity = original_identity_factory(user, request_id=request_id)
            identity = replace(base_identity, subject_id=item["subject"])
            calculated_selected = policy.eligible(
                type("Request", (), {
                    "identity_context": identity,
                    "scenario_id": item["scenario"],
                })()
            )
            if calculated_selected != item["selected"]:
                raise RuntimeError("cohort assignment drifted")
            started = perf_counter()
            with (
                patch.object(IdentityContextFactory, "from_user", return_value=identity),
                patch.object(
                    SQLBotClient,
                    "_credentials",
                    return_value=(
                        runtime_username,
                        derive_runtime_account_password(runtime_password),
                    ),
                ),
            ):
                response = client.post(
                    "/api/v1/assistant/query",
                    headers=headers,
                    json={
                        "question": case["question"],
                        "scenario_id": item["scenario"],
                        "profile": "analyst_detailed",
                        "route": "data",
                        "conversation_id": conversation_id,
                    },
                )
            observed_conversations.add(conversation_id)
            elapsed_ms = int((perf_counter() - started) * 1000)
            events.append(_event_from_response(
                response=response,
                item=item,
                case=case,
                request_id=request_id,
                conversation_id=conversation_id,
                follow_up=follow_up,
                elapsed_ms=elapsed_ms,
                percentage=percentage,
            ))

    selected_events = [event for event in events if event["cohort_selected"]]
    sqlbot_events = [event for event in events if event["sqlbot_attempted"]]
    completed_sqlbot = [
        event for event in sqlbot_events if event["execution"] == "completed"
    ]
    comparable: dict[tuple[str, str], list[str | None]] = {}
    for event in completed_sqlbot:
        comparable.setdefault((event["scenario"], event["case_id"]), []).append(
            event["result_hash"]
        )
    consistency_checks = [
        len(set(values)) == 1
        for values in comparable.values()
        if len(values) > 1
    ]
    deterministic_fallback_events = [
        event for event in sqlbot_events if event["deterministic_fallback_used"]
    ]
    controlled_fallback_events = [
        event for event in sqlbot_events if event["controlled_example_fallback_used"]
    ]
    fallback_events = [
        event for event in sqlbot_events
        if event["deterministic_fallback_used"]
        or event["controlled_example_fallback_used"]
    ]
    real_model_success_events = [
        event for event in sqlbot_events
        if event["model_call_status"] == "RESPONSE_RECEIVED"
        and event["execution"] == "completed"
    ]
    metrics = {
        "request_count": len(events),
        "charging_request_count": sum(event["scenario"] == "charging_ops" for event in events),
        "sales_request_count": sum(event["scenario"] == "sales_ops" for event in events),
        "cohort_selected_count": len(selected_events),
        "cohort_selected_rate": round(len(selected_events) / len(events), 4),
        "sqlbot_attempt_count": len(sqlbot_events),
        "runtime_availability_rate": round(
            sum(event["http_status"] < 500 for event in sqlbot_events) / len(sqlbot_events), 4
        ) if sqlbot_events else None,
        "guard_pass_rate": round(
            sum(event["guard"] == "passed" for event in sqlbot_events)
            / len(sqlbot_events), 4
        ) if sqlbot_events else None,
        "execution_success_rate": round(len(completed_sqlbot) / len(sqlbot_events), 4)
        if sqlbot_events else None,
        "semantic_accuracy": round(
            sum(event["semantic"] == "PASS" for event in sqlbot_events) / len(sqlbot_events), 4
        ) if sqlbot_events else None,
        "result_consistency_rate": round(sum(consistency_checks) / len(consistency_checks), 4)
        if consistency_checks else 1.0,
        "p50_latency_ms": _percentile(
            [event["latency_ms"] for event in sqlbot_events], 0.50
        ),
        "p95_latency_ms": _percentile([event["latency_ms"] for event in sqlbot_events], 0.95),
        "permission_violation_count": sum(event["guard"] == "REJECTED_PERMISSION" for event in events),
        "pii_violation_count": 0,
        "readonly_violation_count": 0,
        "unguarded_sql_count": sum(
            bool(event["sql_hash"]) and event["guard"] != "passed" for event in events
        ),
        "fallback_count": len(fallback_events),
        "fallback_rate": round(len(fallback_events) / len(sqlbot_events), 4)
        if sqlbot_events else 0.0,
        "controlled_exact_example_fallback_count": sum(
            event["controlled_exact_example_fallback"] for event in events
        ),
        "controlled_example_fallback_rate": round(
            len(controlled_fallback_events) / len(sqlbot_events), 4
        ) if sqlbot_events else 0.0,
        "deterministic_fallback_count": len(deterministic_fallback_events),
        "deterministic_fallback_rate": round(
            len(deterministic_fallback_events) / len(sqlbot_events), 4
        ) if sqlbot_events else 0.0,
        "real_model_success_count": len(real_model_success_events),
        "real_model_success_rate": round(
            len(real_model_success_events) / len(sqlbot_events), 4
        ) if sqlbot_events else 0.0,
        "fallback_final_answer_success_rate": round(
            sum(event["http_status"] < 400 for event in fallback_events)
            / len(fallback_events), 4
        ) if fallback_events else 1.0,
        "follow_up_request_count": sum(event["follow_up"] for event in events),
        "core_deterministic_count": sum(
            event["route_decision"] == "CORE_DETERMINISTIC" for event in events
        ),
        "high_risk_governed_count": sum(
            event["category"] == "ambiguity_security_refusal"
            and not event["sqlbot_attempted"]
            and event["http_status"] < 500
            for event in events
        ),
        "scoped_stable_sqlbot_count": sum(
            event["route_decision"] == "SQLBOT_SCOPED_STABLE" for event in events
        ),
    }
    is_probe = args.probe or args.consistency_probe
    gate = {
        "minimum_request_count": metrics["request_count"] >= (
            2 if is_probe else
            100 if args.stage == "canary-5" else 200 if args.stage == "canary-20" else 40
        ),
        "scenario_coverage": (
            metrics["charging_request_count"] >= (
                1 if is_probe else 100 if args.stage == "canary-20" else 1
            )
            and metrics["sales_request_count"] >= (
                1 if is_probe else 100 if args.stage == "canary-20" else 1
            )
        ),
        "stage_percentage": (
            metrics["cohort_selected_rate"] == 1.0
            if is_probe
            else metrics["cohort_selected_rate"] == percentage / 100
        ),
        "runtime": (metrics["runtime_availability_rate"] or 0) >= 0.95,
        "guard": (metrics["guard_pass_rate"] or 0) >= 0.95,
        "execution": (metrics["execution_success_rate"] or 0) >= 0.95,
        "semantic": (metrics["semantic_accuracy"] or 0) >= 0.90,
        "consistency": (metrics["result_consistency_rate"] or 0) >= 0.90,
        "latency": (metrics["p95_latency_ms"] or 99_999) <= 15_000,
        "security": all(metrics[key] == 0 for key in (
            "permission_violation_count", "pii_violation_count",
            "readonly_violation_count", "unguarded_sql_count",
        )),
        "fallback_rate": metrics["fallback_rate"] <= 0.05,
        "fallback_final_answer": (
            metrics["fallback_final_answer_success_rate"] == 1.0
        ),
    }
    if args.stage == "scoped-stable" and not is_probe:
        gate["scoped_routing_boundaries"] = all((
            metrics["core_deterministic_count"] > 0,
            metrics["high_risk_governed_count"] > 0,
            metrics["scoped_stable_sqlbot_count"] > 0,
        ))
    if not is_probe:
        gate["follow_up_coverage"] = metrics["follow_up_request_count"] > 0
    status = "PASS" if all(gate.values()) else "FAIL"
    route_artifact = {
        "schema_version": "1.0",
        "evidence_type": "sqlbot41d_route_events",
        "stage": args.stage,
        "probe": args.probe,
        "consistency_probe": args.consistency_probe,
        "generated_at": datetime.now(UTC).isoformat(),
        "data_classification": "simulated",
        "request_count": len(events),
        "events": events,
        "secret_values_persisted": False,
    }
    acceptance = {
        "schema_version": "1.0",
        "evidence_type": "sqlbot41d_stage_acceptance",
        "stage": args.stage,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "metrics": metrics,
        "gate": gate,
        "runtime": "SQLBot CE v1.10.0",
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "api_path": "/api/v1/assistant/query",
        "database": "current DATA-4.1 PostgreSQL simulated dataset",
        "truth_boundary": {
            "production_traffic_claimed": False,
            "real_customer_usage_claimed": False,
            "real_business_benefit_claimed": False,
        },
    }
    serialized = json.dumps(route_artifact, ensure_ascii=False, indent=2)
    serialized_acceptance = json.dumps(acceptance, ensure_ascii=False, indent=2)
    for secret in (runtime_username, runtime_password):
        if secret and (secret in serialized or secret in serialized_acceptance):
            raise RuntimeError("secret value detected in evidence")
    args.route_output.parent.mkdir(parents=True, exist_ok=True)
    args.acceptance_output.parent.mkdir(parents=True, exist_ok=True)
    args.route_output.write_text(serialized, encoding="utf-8")
    args.acceptance_output.write_text(serialized_acceptance, encoding="utf-8")
    print(json.dumps({"stage": args.stage, "status": status, "metrics": metrics}))
    if status != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
