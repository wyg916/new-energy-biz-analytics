"""Enrich an immutable raw stability attempt with independently sampled resources."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1))
    return ordered[index]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--resources", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError(f"refusing to overwrite evidence: {args.output}")
    report = _read(args.source)
    resources = _read(args.resources)
    events = report.get("events") or []
    sqlbot_events = [event for event in events if event.get("sqlbot_attempted")]
    latencies = [int(event["latency_ms"]) for event in sqlbot_events]
    guard_pass_rate = (
        sum(event.get("guard") == "passed" for event in sqlbot_events)
        / len(sqlbot_events)
        if sqlbot_events else 0.0
    )
    execution_success_rate = (
        sum(event.get("execution") == "completed" for event in sqlbot_events)
        / len(sqlbot_events)
        if sqlbot_events else 0.0
    )
    timeout_count = sum(
        "TIMEOUT" in str(event.get("fallback_reason") or "").upper()
        or "TIMEOUT" in str(event.get("sqlbot_failure_stage") or "").upper()
        for event in sqlbot_events
    )
    samples = resources.get("samples") or []
    report.update({
        "api_5xx_error_rate": round(
            sum(int(event.get("http_status", 500)) >= 500 for event in events)
            / len(events), 4
        ) if events else 1.0,
        "guard_pass_rate": round(guard_pass_rate, 4),
        "guard_reject_rate": round(1.0 - guard_pass_rate, 4),
        "execution_success_rate": round(execution_success_rate, 4),
        "timeout_count": timeout_count,
        "timeout_rate": round(timeout_count / len(sqlbot_events), 4)
        if sqlbot_events else 1.0,
        "p50_sqlbot_api_latency_ms": _percentile(latencies, 0.50),
        "p95_sqlbot_api_latency_ms": _percentile(latencies, 0.95),
        "runtime_resource_monitor": {
            "status": resources.get("status"),
            "sample_count": len(samples),
            "started_at": resources.get("started_at"),
            "finished_at": resources.get("finished_at"),
            "peak_cpu_percent": max(
                (float(sample["cpu_percent"]) for sample in samples),
                default=None,
            ),
            "initial_memory_percent": (
                float(samples[0]["memory_percent"]) if samples else None
            ),
            "final_memory_percent": (
                float(samples[-1]["memory_percent"]) if samples else None
            ),
            "peak_memory_percent": max(
                (float(sample["memory_percent"]) for sample in samples),
                default=None,
            ),
            "sampling_note": (
                "full-window memory samples are embedded by the acceptance wrapper; "
                "CPU sampling began after the missing CPU field was detected"
            ),
        },
    })
    checks = report.setdefault("checks", {})
    checks.update({
        "guard": guard_pass_rate >= 0.95,
        "execution": execution_success_rate >= 0.95,
        "runtime_cpu_observed": resources.get("status") == "PASS" and bool(samples),
    })
    report["status"] = (
        "PASS"
        if report.get("status") == "PASS" and all(checks.values())
        else "FAIL"
    )
    report["enrichment"] = {
        "source_raw_evidence": args.source.name,
        "resource_evidence": args.resources.name,
        "derived_only_from_preserved_raw_events": True,
        "thresholds_lowered": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": report["status"], "checks": checks}, sort_keys=True))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
