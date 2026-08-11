"""Observe a real 20% controlled SQLBot window for at least 30 minutes."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter, sleep
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.core.database import SessionLocal
from app.main import app
from app.models.auth import User
from app.platform.identity import IdentityContextFactory
from app.query_engines.sqlbot.client import SQLBotClient
from app.query_engines.sqlbot.credentials import derive_runtime_account_password
from run_sqlbot_canary_acceptance import (
    SCENARIOS,
    _cohort,
    _configure,
    _event_from_response,
    _load_cases,
    _question,
    _runtime_credentials,
)


def _database_connections() -> int:
    with SessionLocal() as db:
        return int(db.scalar(text(
            "SELECT COUNT(*) FROM pg_stat_activity WHERE datname = current_database()"
        )) or 0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--sqlbot-base-url", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=12.0)
    parser.add_argument("--duration-minutes", type=float, default=30.0)
    parser.add_argument("--interval-seconds", type=float, default=30.0)
    args = parser.parse_args()
    if args.duration_minutes < 30:
        raise ValueError("SQLBot 4.1D stability window must be at least 30 minutes")

    acceptance_args = argparse.Namespace(
        sqlbot_base_url=args.sqlbot_base_url,
        timeout_seconds=args.timeout_seconds,
    )
    cohort = _cohort("canary-20")
    _configure("canary-20", cohort, acceptance_args)
    cases = _load_cases(args.source)
    selected = {
        scenario: next(
            item for item in cohort
            if item["scenario"] == scenario and item["selected"]
        )
        for scenario in SCENARIOS
    }
    controls = {
        scenario: next(
            item for item in cohort
            if item["scenario"] == scenario and not item["selected"]
        )
        for scenario in SCENARIOS
    }

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "analyst"))
        if user is None:
            raise RuntimeError("controlled analyst user is unavailable")
        runtime_username, runtime_password = _runtime_credentials(db, user)
        original_identity_factory = IdentityContextFactory.from_user

    events = []
    samples = []
    observed_conversations: set[str] = set()
    started = perf_counter()
    started_at = datetime.now(UTC)
    run_token = started_at.strftime("%H%M%S")
    initial_connections = _database_connections()
    iteration = 0
    derived_runtime_password = derive_runtime_account_password(runtime_password)
    with (
        TestClient(app) as client,
        httpx.Client(timeout=5.0) as runtime_health_client,
    ):
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "analyst", "password": "AlphaAnalyst!2026"},
        )
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        while perf_counter() - started < args.duration_minutes * 60:
            scenario = SCENARIOS[iteration % len(SCENARIOS)]
            item = selected[scenario] if iteration % 5 == 0 else controls[scenario]
            case = _question(cases, item, iteration)
            request_id = f"SQLBOT-41D-STABILITY-{iteration + 1:04d}"
            identity = replace(
                original_identity_factory(user, request_id=request_id),
                subject_id=item["subject"],
            )
            conversation_id = (
                f"s41d-stability-{run_token}-{scenario}-canary"
                if item["selected"]
                else f"s41d-stability-{run_token}-{iteration + 1:04d}"
            )
            follow_up = conversation_id in observed_conversations
            request_started = perf_counter()
            with (
                patch.object(IdentityContextFactory, "from_user", return_value=identity),
                patch.object(
                    SQLBotClient,
                    "_credentials",
                    return_value=(runtime_username, derived_runtime_password),
                ),
            ):
                response = client.post(
                    "/api/v1/assistant/query",
                    headers=headers,
                    json={
                        "question": case["question"],
                        "scenario_id": scenario,
                        "profile": "analyst_detailed",
                        "route": "data",
                        "conversation_id": conversation_id,
                    },
                )
            observed_conversations.add(conversation_id)
            latency = int((perf_counter() - request_started) * 1000)
            event = _event_from_response(
                response=response,
                item=item,
                case=case,
                request_id=request_id,
                conversation_id=conversation_id,
                follow_up=follow_up,
                elapsed_ms=latency,
                percentage=20.0,
            )
            events.append(event)
            health_started = perf_counter()
            try:
                health_status = runtime_health_client.get(
                    args.sqlbot_base_url.split("/api/v1", 1)[0] + "/",
                ).status_code
            except httpx.HTTPError:
                health_status = 0
            samples.append({
                "sample": iteration + 1,
                "sampled_at": datetime.now(UTC).isoformat(),
                "elapsed_seconds": round(perf_counter() - started, 3),
                "runtime_health_http_status": health_status,
                "runtime_health_latency_ms": int((perf_counter() - health_started) * 1000),
                "database_connections": _database_connections(),
                "api_http_status": response.status_code,
                "route_decision": event["route_decision"],
                "final_engine": event["final_engine"],
                "fallback_used": (
                    event["deterministic_fallback_used"]
                    or event["controlled_example_fallback_used"]
                ),
                "latency_ms": latency,
            })
            iteration += 1
            next_sample_at = started + iteration * args.interval_seconds
            while True:
                remaining = next_sample_at - perf_counter()
                if remaining <= 0:
                    break
                sleep(min(remaining, 30.0))

    elapsed_seconds = perf_counter() - started
    final_connections = _database_connections()
    sqlbot_events = [event for event in events if event["sqlbot_attempted"]]
    deterministic_fallbacks = [
        event for event in sqlbot_events if event["deterministic_fallback_used"]
    ]
    controlled_fallbacks = [
        event for event in sqlbot_events if event["controlled_example_fallback_used"]
    ]
    fallbacks = [
        event for event in sqlbot_events
        if event["deterministic_fallback_used"]
        or event["controlled_example_fallback_used"]
    ]
    real_model_successes = [
        event for event in sqlbot_events
        if event["model_call_status"] == "RESPONSE_RECEIVED"
        and event["execution"] == "completed"
    ]
    sqlbot_latencies = sorted(event["latency_ms"] for event in sqlbot_events)
    p95_index = max(
        0,
        min(len(sqlbot_latencies) - 1, math.ceil(len(sqlbot_latencies) * 0.95) - 1),
    )
    p50_index = max(
        0,
        min(len(sqlbot_latencies) - 1, math.ceil(len(sqlbot_latencies) * 0.50) - 1),
    )
    p95 = sqlbot_latencies[p95_index] if sqlbot_latencies else None
    p50 = sqlbot_latencies[p50_index] if sqlbot_latencies else None
    guard_pass_rate = (
        sum(event["guard"] == "passed" for event in sqlbot_events)
        / len(sqlbot_events)
        if sqlbot_events else 0.0
    )
    execution_success_rate = (
        sum(event["execution"] == "completed" for event in sqlbot_events)
        / len(sqlbot_events)
        if sqlbot_events else 0.0
    )
    timeout_count = sum(
        "TIMEOUT" in str(event.get("fallback_reason") or "").upper()
        or "TIMEOUT" in str(event.get("sqlbot_failure_stage") or "").upper()
        for event in sqlbot_events
    )
    runtime_health_success_count = sum(
        sample["runtime_health_http_status"] == 200 for sample in samples
    )
    runtime_health_rate = (
        runtime_health_success_count / len(samples) if samples else 0.0
    )
    checks = {
        "elapsed_at_least_30_minutes": elapsed_seconds >= 30 * 60,
        "runtime_health": runtime_health_rate >= 0.95,
        "api_no_500": all(event["http_status"] < 500 for event in events),
        "both_scenarios": set(event["scenario"] for event in events) == set(SCENARIOS),
        "sqlbot_primary_observed": bool(sqlbot_events),
        "fallback_rate": (len(fallbacks) / len(sqlbot_events) if sqlbot_events else 1) <= 0.05,
        "fallback_final_answer": all(
            event["http_status"] < 400 for event in fallbacks
        ),
        "guard": guard_pass_rate >= 0.95,
        "execution": execution_success_rate >= 0.95,
        "p95_latency": p95 is not None and p95 <= 15_000,
        "database_connection_growth": final_connections <= initial_connections + 5,
        "database_connection_ceiling": max(
            sample["database_connections"] for sample in samples
        ) <= 50,
        "circuit_breaker": all(
            event["circuit_breaker_state"] in {"CLOSED", "NOT_APPLICABLE"}
            for event in events
        ),
        "security": all(
            not event["sql_hash"] or event["guard"] == "passed" for event in events
        ),
    }
    artifact = {
        "schema_version": "1.0",
        "evidence_type": "sqlbot41d_canary20_stability",
        "generated_at": datetime.now(UTC).isoformat(),
        "started_at": started_at.isoformat(),
        "status": "PASS" if all(checks.values()) else "FAIL",
        "configured_duration_minutes": args.duration_minutes,
        "observed_elapsed_seconds": round(elapsed_seconds, 3),
        "sample_count": len(samples),
        "request_count": len(events),
        "sqlbot_attempt_count": len(sqlbot_events),
        "fallback_count": len(fallbacks),
        "fallback_rate": round(len(fallbacks) / len(sqlbot_events), 4)
        if sqlbot_events else None,
        "controlled_example_fallback_count": len(controlled_fallbacks),
        "controlled_example_fallback_rate": round(
            len(controlled_fallbacks) / len(sqlbot_events), 4
        ) if sqlbot_events else None,
        "deterministic_fallback_count": len(deterministic_fallbacks),
        "deterministic_fallback_rate": round(
            len(deterministic_fallbacks) / len(sqlbot_events), 4
        ) if sqlbot_events else None,
        "real_model_success_count": len(real_model_successes),
        "real_model_success_rate": round(
            len(real_model_successes) / len(sqlbot_events), 4
        ) if sqlbot_events else None,
        "fallback_final_answer_success_rate": round(
            sum(event["http_status"] < 400 for event in fallbacks)
            / len(fallbacks), 4
        ) if fallbacks else 1.0,
        "follow_up_request_count": sum(event["follow_up"] for event in events),
        "api_5xx_error_rate": round(
            sum(event["http_status"] >= 500 for event in events) / len(events), 4
        ) if events else 1.0,
        "guard_pass_rate": round(guard_pass_rate, 4),
        "guard_reject_rate": round(1.0 - guard_pass_rate, 4),
        "execution_success_rate": round(execution_success_rate, 4),
        "timeout_count": timeout_count,
        "timeout_rate": round(timeout_count / len(sqlbot_events), 4)
        if sqlbot_events else 1.0,
        "p50_sqlbot_api_latency_ms": p50,
        "p95_sqlbot_api_latency_ms": p95,
        "runtime_health_success_count": runtime_health_success_count,
        "runtime_health_rate": round(runtime_health_rate, 4),
        "initial_database_connections": initial_connections,
        "final_database_connections": final_connections,
        "max_database_connections": max(
            sample["database_connections"] for sample in samples
        ),
        "checks": checks,
        "samples": samples,
        "events": events,
        "secret_values_persisted": False,
        "truth_boundary": {
            "controlled_acceptance_window": True,
            "production_traffic_claimed": False,
            "real_customer_usage_claimed": False,
        },
    }
    serialized = json.dumps(artifact, ensure_ascii=False, indent=2)
    for secret in (runtime_username, runtime_password):
        if secret and secret in serialized:
            raise RuntimeError("secret value detected in stability evidence")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(serialized, encoding="utf-8")
    print(json.dumps({
        "status": artifact["status"],
        "elapsed_seconds": artifact["observed_elapsed_seconds"],
        "request_count": artifact["request_count"],
        "sqlbot_attempt_count": artifact["sqlbot_attempt_count"],
        "fallback_rate": artifact["fallback_rate"],
        "p95_sqlbot_api_latency_ms": artifact["p95_sqlbot_api_latency_ms"],
    }))
    if artifact["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
