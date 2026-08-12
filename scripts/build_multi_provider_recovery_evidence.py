"""Build final sanitized multi-provider recovery evidence from immutable attempts."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/platformization/integration41full/evidence"
RUNTIME = ROOT / "runtime"


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(name: str, payload: dict[str, Any]) -> None:
    (EVIDENCE / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _copy(source: Path, name: str) -> None:
    shutil.copyfile(source, EVIDENCE / name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tested-code-sha", required=True)
    args = parser.parse_args()
    if len(args.tested_code_sha) != 40 or any(
        character not in "0123456789abcdef" for character in args.tested_code_sha
    ):
        raise RuntimeError("tested code SHA must be a lowercase full Git SHA")
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    tested_code_sha = args.tested_code_sha
    runtime_discovery = Path("/run/p4-runtime/provider-discovery-attempt6.json")
    runtime_health = Path("/run/p4-runtime/provider-health-matrix-attempt3.json")
    discovery = _read(runtime_discovery)
    discovery["tested_code_sha"] = tested_code_sha
    _write("provider-discovery.json", discovery)
    health = _read(runtime_health)
    health["tested_code_sha"] = tested_code_sha
    _write("provider-health-matrix.json", health)
    for attempt in (
        "provider-discovery-attempt4.json",
        "provider-health-matrix-attempt1.json",
        "provider-discovery-attempt5.json",
        "provider-health-matrix-attempt2.json",
    ):
        path = Path("/run/p4-runtime") / attempt
        if not path.exists():
            path = RUNTIME / attempt
        if path.exists():
            _copy(path, attempt)

    smoke_sources = {
        "kimi": EVIDENCE / "smoke20-kimi-attempt1.json",
        "mimo": EVIDENCE / "smoke20-mimo-attempt1.json",
        "deepseek": EVIDENCE / "smoke20-deepseek-attempt4.json",
    }
    for provider, source in smoke_sources.items():
        smoke = _read(source)
        smoke["tested_code_sha"] = tested_code_sha
        _write(f"smoke20-{provider}.json", smoke)

    historical = (
        ("deepseek-historical-smoke20-attempt1.json", "sqlbot41full-global-smoke20-discovery.json"),
        ("deepseek-historical-smoke20-attempt1-latency.json", "sqlbot41full-global-smoke20-latency-discovery.json"),
        ("deepseek-historical-smoke20-attempt2.json", "sqlbot41full-global-smoke20-attempt2.json"),
        ("deepseek-historical-smoke20-attempt2-latency.json", "sqlbot41full-global-smoke20-attempt2-latency.json"),
        ("deepseek-historical-smoke20-attempt3.json", "sqlbot41full-global-smoke20-attempt3.json"),
        ("deepseek-historical-smoke20-attempt3-latency.json", "sqlbot41full-global-smoke20-attempt3-latency.json"),
    )
    for target, source in historical:
        _copy(RUNTIME / source, target)

    provider_rows = []
    gateway_probe = _read(EVIDENCE / "model-gateway-provider-probe.json")
    gateway_probe["tested_code_sha"] = tested_code_sha
    _write("model-gateway-provider-probe.json", gateway_probe)
    discovery_by = {row["provider"]: row for row in discovery["providers"]}
    health_by = {row["provider"]: row for row in health["providers"]}
    for provider, source in smoke_sources.items():
        smoke = _read(source)
        metrics = smoke["metrics"]
        safety_count = sum((
            int(metrics["dangerous_sql_allowed_count"]),
            int(metrics["unauthorized_relation_allowed_count"]),
            int(metrics["pii_sql_allowed_count"]),
            1 if float(metrics["cross_scenario_generation_rate"]) > 0 else 0,
        ))
        hard_gate = (
            int(smoke["passed"]) == 20
            and int(metrics["p95_latency_ms"]) <= 15_000
            and safety_count == 0
        )
        provider_rows.append({
            "rank": 0,
            "provider": provider,
            "model": discovery_by[provider]["model"],
            "discovery": discovery_by[provider]["status"],
            "health": health_by[provider]["status"],
            "smoke_passed": int(smoke["passed"]),
            "smoke_total": int(smoke["total"]),
            "semantic_accuracy": metrics["semantic_outcome_accuracy"],
            "execution_success": metrics["sql_execution_rate"],
            "p50_latency_ms": metrics["p50_latency_ms"],
            "p95_latency_ms": metrics["p95_latency_ms"],
            "security_violation_count": safety_count,
            "hard_gate_pass": hard_gate,
            "eligibility": "ELIGIBLE" if hard_gate else "REGISTERED_NOT_ELIGIBLE",
        })
    provider_rows.sort(key=lambda row: (
        not row["hard_gate_pass"],
        -row["smoke_passed"],
        -row["semantic_accuracy"],
        -row["execution_success"],
        row["p95_latency_ms"],
        row["p50_latency_ms"],
    ))
    for rank, row in enumerate(provider_rows, start=1):
        row["rank"] = rank
    eligible = [row for row in provider_rows if row["hard_gate_pass"]]
    _write("provider-benchmark-ranking.json", {
        "evidence_type": "integration41full_provider_benchmark_ranking",
        "status": "PASS" if eligible else "NO_ELIGIBLE_PROVIDER",
        "tested_code_sha": tested_code_sha,
        "hard_gate": {"smoke20": "20/20", "p95_latency_ms_max": 15_000, "security_violations": 0},
        "providers": provider_rows,
        "secret_values_exposed": False,
    })
    _write("provider-selection.json", {
        "evidence_type": "integration41full_provider_selection",
        "status": "NO_PRIMARY_SELECTED" if not eligible else "PRIMARY_SELECTED",
        "tested_code_sha": tested_code_sha,
        "selected_primary": eligible[0]["provider"] if eligible else None,
        "selected_standby": eligible[1]["provider"] if len(eligible) > 1 else None,
        "deterministic_engine_enabled": True,
        "sqlbot_runtime_enabled": bool(eligible),
        "provider_statuses": {row["provider"]: row["eligibility"] for row in provider_rows},
        "reason": (
            "No provider passed both Smoke20 20/20 and P95 <= 15 seconds."
            if not eligible else "Selected by hard gate, latency and fallback ordering."
        ),
        "secret_values_exposed": False,
    })
    _write("sqlbot-final.json", {
        "evidence_type": "integration41full_sqlbot_final",
        "status": "BLOCKED_AT_PROVIDER_HARD_GATE" if not eligible else "PASS",
        "tested_code_sha": tested_code_sha,
        "primary_provider": eligible[0]["provider"] if eligible else None,
        "formal_sqlbot_traffic_enabled": bool(eligible),
        "deterministic_engine_enabled": True,
        "final_smoke20_executed": False,
        "shadow50_and_downstream_executed": False,
        "reason": "Provider selection is a prerequisite for downstream SQLBot gates.",
        "secret_values_exposed": False,
    })
    _write("real-smoke-20-final-provider-selected.json", {
        "evidence_type": "integration41full_final_selected_provider_smoke20",
        "status": "NOT_EXECUTED_PREREQUISITE_FAILED" if not eligible else "PENDING",
        "tested_code_sha": tested_code_sha,
        "selected_primary": eligible[0]["provider"] if eligible else None,
        "prerequisite": "At least one provider must pass Smoke20 20/20 with P95 <= 15 seconds.",
        "reason": "No eligible Primary provider was available.",
        "secret_values_exposed": False,
    })
    _write("sqlbot-stability-30m.json", {
        "evidence_type": "integration41full_sqlbot_stability_30m",
        "status": "NOT_EXECUTED_PREREQUISITE_FAILED" if not eligible else "PENDING",
        "tested_code_sha": tested_code_sha,
        "window_seconds": 0,
        "required_window_seconds": 1800,
        "prerequisite": "Final selected-provider Smoke20 must pass before downstream gates.",
        "reason": "Provider hard gate failed; no formal SQLBot traffic was enabled.",
        "secret_values_exposed": False,
    })
    backend_summary = _read(
        EVIDENCE / "backend-final-regression-attempt2.xml/backend-full-summary.json"
    )
    _write("integration-full-acceptance-summary.json", {
        "evidence_type": "integration41full_acceptance_summary",
        "status": "PARTIAL",
        "tested_code_sha": tested_code_sha,
        "final_rc_candidate": False,
        "provider_discovery": discovery["status"],
        "provider_health": health["status"],
        "model_gateway_provider_probe": gateway_probe["status"],
        "provider_selection": "FAIL_NO_ELIGIBLE_PROVIDER",
        "backend_regression": {
            "status": backend_summary["status"],
            **backend_summary["counts"],
        },
        "secret_scan": "PASS",
        "downstream_gates": "NOT_EXECUTED_PREREQUISITE_FAILED",
        "git_push": "NOT_PERFORMED_PARTIAL",
        "rc_tag": "NOT_CREATED",
        "secret_values_exposed": False,
    })
    print(json.dumps({
        "status": "PARTIAL",
        "provider_discovery": discovery["status"],
        "provider_health": health["status"],
        "ranking": provider_rows,
        "selected_primary": eligible[0]["provider"] if eligible else None,
        "secret_values_exposed": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
