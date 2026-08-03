"""Verify P5A fail-closed readiness, liveness, dependency recovery, and fallbacks."""

from __future__ import annotations

import argparse
import json
import os
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE_COMPOSE = ROOT / "deploy" / "preproduction" / "compose.yaml"
OVERRIDE_COMPOSE = Path(os.getenv(
    "ACCEPTANCE_OVERRIDE_COMPOSE",
    str(ROOT / "deploy" / "production-acceptance" / "p5a.override.yaml"),
))
PROJECT = os.getenv("ACCEPTANCE_COMPOSE_PROJECT", "renewable-p5a-remediation")
BASE_URL = os.getenv("ACCEPTANCE_API_BASE_URL", "https://127.0.0.1:8445/api/v1")
HOST = os.getenv("ACCEPTANCE_HOST", "p5a.localhost")
SCOPE = os.getenv("ACCEPTANCE_SCOPE", "p5a")
CONTAINERS = {
    service: f"{PROJECT}-{service}-1" for service in ("api", "redis", "db", "vault", "oidc")
}


def command(*args: str, capture: bool = False) -> str:
    process = subprocess.run(
        list(args), cwd=ROOT, text=True, encoding="utf-8", capture_output=capture,
    )
    if process.returncode:
        detail = (process.stderr or "").strip() if capture else ""
        raise RuntimeError(detail or f"command failed without destructive cleanup: {args[:3]}")
    return process.stdout.strip() if capture else ""


def compose(*args: str, capture: bool = False) -> str:
    return command(
        "docker", "compose", "-p", PROJECT,
        "-f", str(BASE_COMPOSE), "-f", str(OVERRIDE_COMPOSE),
        *args, capture=capture,
    )


def request(
    path: str,
    *,
    token: str | None = None,
    payload: dict | None = None,
    method: str | None = None,
) -> tuple[int, dict]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Host": HOST}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        f"{BASE_URL}{path}", data=body, headers=headers, method=method,
    )
    try:
        with urllib.request.urlopen(
            req, timeout=15, context=ssl._create_unverified_context(),
        ) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            payload_body = json.loads(exc.read().decode("utf-8"))
        except Exception:
            payload_body = {}
        return exc.code, payload_body
    except (OSError, TimeoutError):
        return 0, {}


def status(path: str) -> int:
    return request(path)[0]


def wait_status(path: str, expected: int, timeout: float = 120) -> float:
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        if status(path) == expected:
            return round(time.monotonic() - started, 3)
        time.sleep(1)
    raise RuntimeError(f"{path} did not reach {expected}")


def restart_count(service: str) -> int:
    value = command(
        "docker", "inspect", CONTAINERS[service],
        "--format", "{{.RestartCount}}", capture=True,
    )
    return int(value)


def wait_health(service: str, timeout: float = 180) -> float:
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        state = json.loads(command(
            "docker", "inspect", CONTAINERS[service], "--format", "{{json .State}}",
            capture=True,
        ))
        health = (state.get("Health") or {}).get("Status")
        if state.get("Status") == "running" and health in {None, "healthy"}:
            return round(time.monotonic() - started, 3)
        time.sleep(1)
    raise RuntimeError(f"{service} did not become healthy")


def wait_running(service: str, timeout: float = 60) -> float:
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        state = json.loads(command(
            "docker", "inspect", CONTAINERS[service], "--format", "{{json .State}}",
            capture=True,
        ))
        if state.get("Status") == "running":
            return round(time.monotonic() - started, 3)
        time.sleep(1)
    raise RuntimeError(f"{service} did not enter running state")


def governance_counts() -> dict:
    code = (
        "import json; from sqlalchemy import func, select; "
        "from app.core.database import SessionLocal; "
        "from app.governance.models import GovernanceAuditEvent, LegalHold, SecurityAlert; "
        "db=SessionLocal(); "
        "print(json.dumps({'governance_audit_events': int(db.scalar(select(func.count()).select_from(GovernanceAuditEvent)) or 0), "
        "'security_alerts': int(db.scalar(select(func.count()).select_from(SecurityAlert)) or 0), "
        "'open_security_alerts': int(db.scalar(select(func.count()).select_from(SecurityAlert).where(SecurityAlert.status.in_(['OBSERVING','OPEN']))) or 0), "
        "'legal_holds': int(db.scalar(select(func.count()).select_from(LegalHold)) or 0)})); db.close()"
    )
    output = command(
        "docker", "exec", CONTAINERS["api"],
        "python", "scripts/p4_entrypoint.py", "python", "-c", code,
        capture=True,
    )
    return json.loads(output.splitlines()[-1])


def fault_probe(service: str, token: str) -> dict:
    if service == "db":
        probe_status, probe = request(
            "/knowledge/retrieval/test",
            token=token,
            payload={
                "query": "充电收入指标口径",
                "scenario_id": "charging_ops",
                "trace_id": "P5A-DB-FAULT-RAG",
                "run_id": "P5A-FAULT-RECOVERY",
                "limit": 3,
            },
        )
        citations = probe.get("citations") if isinstance(probe, dict) else None
        return {
            "probe": "rag_retrieval_while_database_unavailable",
            "http_status": probe_status,
            "controlled_unavailable": probe_status in {0, 500, 502, 503},
            "citation_count": len(citations) if isinstance(citations, list) else 0,
            "fabricated_citation": bool(citations),
        }
    if service == "vault":
        output = command(
            "docker", "exec", CONTAINERS["api"],
            "python", "scripts/p4_entrypoint.py", "python",
            "scripts/verify_p4_secret_fail_closed.py",
            capture=True,
        )
        payload = json.loads(output.splitlines()[-1])
        return {
            "probe": "credential_reference_while_vault_unavailable",
            "fail_closed": payload.get("fail_closed") is True,
            "error_code": payload.get("error_code"),
            "plaintext_fallback_used": payload.get("plaintext_fallback_used"),
            "secret_values_printed": payload.get("secret_values_printed"),
        }
    if service == "oidc":
        probe_status, probe = request("/auth/oidc/status")
        provider_status = probe.get("status") if isinstance(probe, dict) else None
        return {
            "probe": "oidc_provider_health_while_provider_unavailable",
            "http_status": probe_status,
            "provider_status": provider_status,
            "controlled_unavailable": (
                probe_status == 200 and provider_status == "UNAVAILABLE"
            ),
        }
    return {"probe": "readiness_and_liveness_only", "controlled_unavailable": True}


def exercise(service: str, token: str) -> dict:
    before = restart_count(service)
    compose("stop", service)
    try:
        readiness_failed_seconds = wait_status("/health/ready", 503)
        liveness_during_fault = status("/health")
        probe = fault_probe(service, token)
    finally:
        # Never leave the acceptance stack in an injected-fault state, even if
        # the fail-closed assertion itself raises.
        compose("start", service)
    if service == "vault":
        running_seconds = wait_running(service)
        compose("run", "--rm", "vault-bootstrap")
    else:
        running_seconds = None
    healthy_seconds = wait_health(service)
    recovered_seconds = wait_status("/health/ready", 200)
    after = restart_count(service)
    return {
        "readiness_failed_closed": True,
        "readiness_failed_seconds": readiness_failed_seconds,
        "liveness_http_status_during_fault": liveness_during_fault,
        "liveness_process_semantics_preserved": liveness_during_fault == 200,
        "container_healthy_seconds": healthy_seconds,
        "container_running_before_recovery_seconds": running_seconds,
        "readiness_recovered_seconds": recovered_seconds,
        "restart_count_before": before,
        "restart_count_after": after,
        "restart_count_reset_by_manual_start": after < before,
        "unexpected_restart": after > before,
        "fault_probe": probe,
    }


def acceptance_identity() -> tuple[str, str]:
    code = (
        "import sys; sys.path.insert(0, '/app/scripts'); "
        "import json; from run_p4_capacity_soak import token_for; "
        "token, session_id = token_for('analyst'); "
        "print(json.dumps({'token': token, 'session_id': session_id}))"
    )
    output = command(
        "docker", "exec", CONTAINERS["api"],
        "python", "scripts/p4_entrypoint.py", "python", "-c", code,
        capture=True,
    )
    lines = output.splitlines()
    if not lines:
        raise RuntimeError("acceptance OIDC session creation returned no token")
    payload = json.loads(lines[-1])
    return str(payload["token"]), str(payload["session_id"])


def revoke_acceptance_session(session_id: str) -> None:
    code = (
        "from app.preproduction.oidc import OIDCSessionStore; "
        f"OIDCSessionStore().revoke_session({session_id!r}); "
        "print({'session_revoked': True})"
    )
    command(
        "docker", "exec", CONTAINERS["api"],
        "python", "scripts/p4_entrypoint.py", "python", "-c", code,
        capture=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if status("/health/ready") != 200 or status("/health") != 200:
        raise SystemExit(f"{SCOPE.upper()} readiness and liveness must be healthy before fault injection")
    started_at = datetime.now(UTC)
    global_restarts_before = {service: restart_count(service) for service in CONTAINERS}
    token, session_id = acceptance_identity()
    try:
        governance_before = governance_counts()
        services = {
            service: exercise(service, token)
            for service in ("redis", "db", "vault", "oidc")
        }
        rag_status, rag = request("/knowledge/runtime", token=token)
        assistant_status, assistant = request(
            "/assistant/query",
            token=token,
            payload={
                "question": "2026年6月充电收入是多少？",
                "scenario_id": "charging_ops",
                "profile": "executive_brief",
                "conversation_id": "p5a-fault-fallback",
            },
        )
        snapshot_status, snapshot = request("/production-acceptance/snapshot", token=token)
        governance_after = governance_counts()
    finally:
        revoke_acceptance_session(session_id)
    running_services = compose("ps", "--services", capture=True).splitlines()
    sqlbot_containers = [service for service in running_services if service == "sqlbot"]
    global_restarts_after = {service: restart_count(service) for service in CONTAINERS}
    global_restart_changes = {
        service: {
            "before": global_restarts_before[service],
            "after": global_restarts_after[service],
            "reset_by_manual_start": (
                global_restarts_after[service] < global_restarts_before[service]
            ),
            "unexpected": (
                global_restarts_after[service] > global_restarts_before[service]
            ),
        }
        for service in CONTAINERS
    }
    fallback = {
        "rag_index_unavailable": rag_status == 200 and rag.get("vector_status") == "VECTOR_DEFERRED_POST_P5",
        "rag_runtime_mode": rag.get("retrieval_mode"),
        "rag_vector_status": rag.get("vector_status"),
        "rag_sqlbot_runtime": rag.get("sqlbot_runtime"),
        "sqlbot_container_count": len([item for item in sqlbot_containers if item]),
        "sqlbot_engine_enabled": snapshot.get("runtime_contract", {}).get("sqlbot_engine_enabled"),
        "sqlbot_canary_eligible": snapshot.get("runtime_contract", {}).get("sqlbot_canary_eligible"),
        "deterministic_answer_http_status": assistant_status,
        "deterministic_answer_completed": (
            assistant_status == 200
            and (assistant.get("data_query_evidence") or {}).get("status") == "completed"
            and (assistant.get("response") or {}).get("refused") is False
            and (assistant.get("model_call") or {}).get("status") == "NOT_REQUIRED_DETERMINISTIC_COMPOSITION"
        ),
        "sqlbot_failure_impacted_primary_answers": 0 if (
            assistant_status == 200
            and (assistant.get("data_query_evidence") or {}).get("status") == "completed"
            and (assistant.get("response") or {}).get("refused") is False
        ) else 1,
        "snapshot_http_status": snapshot_status,
    }
    governance = {
        "before": governance_before,
        "after": governance_after,
        "audit_event_delta": (
            governance_after["governance_audit_events"]
            - governance_before["governance_audit_events"]
        ),
        "security_alert_count_preserved": (
            governance_after["security_alerts"] >= governance_before["security_alerts"]
        ),
        "legal_hold_count_preserved": (
            governance_after["legal_holds"] == governance_before["legal_holds"]
        ),
    }
    passed = (
        all(
            item["readiness_failed_closed"]
            and item["liveness_process_semantics_preserved"]
            and not item["unexpected_restart"]
            and item["fault_probe"].get(
                "controlled_unavailable", item["fault_probe"].get("fail_closed")
            ) is True
            for item in services.values()
        )
        and services["db"]["fault_probe"]["fabricated_citation"] is False
        and services["vault"]["fault_probe"]["plaintext_fallback_used"] is False
        and services["vault"]["fault_probe"]["secret_values_printed"] is False
        and fallback["rag_index_unavailable"]
        and fallback["sqlbot_container_count"] == 0
        and fallback["sqlbot_engine_enabled"] is False
        and fallback["sqlbot_canary_eligible"] is False
        and fallback["rag_sqlbot_runtime"] in {"RUNTIME_PENDING", "NOT_INCLUDED_IN_THIS_RELEASE"}
        and fallback["sqlbot_failure_impacted_primary_answers"] == 0
        and governance["audit_event_delta"] > 0
        and governance["security_alert_count_preserved"]
        and governance["legal_hold_count_preserved"]
        and not any(item["unexpected"] for item in global_restart_changes.values())
    )
    result = {
        "evidence_type": f"{SCOPE}_fault_recovery",
        "status": "PASS" if passed else "FAIL",
        "environment": f"{SCOPE.upper()} production-acceptance, not production",
        "data_classification": "simulated",
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "services": services,
        "global_restart_counts": global_restart_changes,
        "global_unexpected_restart_count": sum(
            item["unexpected"] for item in global_restart_changes.values()
        ),
        "fallbacks": fallback,
        "governance_observability": governance,
        "volumes_deleted": False,
        "source_database_reinitialized": False,
        "secret_values_printed": False,
        "production_release_authorized": False,
        "production_traffic_switched": False,
    }
    serialized = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(serialized.encode("utf-8"))
    print(json.dumps({"status": result["status"], "services": list(services), "fallbacks": fallback}, ensure_ascii=False))
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
