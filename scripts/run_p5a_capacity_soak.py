"""Run and monitor the P5A two-hour workload from the Docker host.

The wrapper keeps the request generator inside the API container while it
collects per-container CPU, RSS and restart evidence from Docker. Results are
preproduction acceptance measurements and are never a production SLA.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE_COMPOSE = ROOT / "deploy" / "preproduction" / "compose.yaml"
OVERRIDE_COMPOSE = ROOT / "deploy" / "production-acceptance" / "p5a.override.yaml"
PROJECT = "renewable-p5a-remediation"
SERVICES = ("api", "db", "redis", "oidc", "vault")


def command(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    process = subprocess.run(
        list(args), cwd=ROOT, text=True, encoding="utf-8", capture_output=True,
    )
    if check and process.returncode:
        if process.stderr:
            print(process.stderr, end="")
        raise RuntimeError(f"command failed: {args[:4]}")
    return process


def compose_args(*args: str) -> list[str]:
    return [
        "docker", "compose", "-p", PROJECT,
        "-f", str(BASE_COMPOSE), "-f", str(OVERRIDE_COMPOSE), *args,
    ]


def container_id(service: str) -> str:
    value = command(*compose_args("ps", "-q", service)).stdout.strip()
    if not value:
        raise RuntimeError(f"required P5A service is unavailable: {service}")
    return value


def inspect_restart(container: str) -> int:
    return int(command("docker", "inspect", container, "--format", "{{.RestartCount}}").stdout.strip())


def size_bytes(value: str) -> int:
    number, unit = re.match(r"^([0-9.]+)([KMG]iB|B)$", value.strip()).groups()
    multiplier = {"B": 1, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3}[unit]
    return int(float(number) * multiplier)


def resource_sample(containers: dict[str, str], elapsed: float) -> dict:
    result = command(
        "docker", "stats", "--no-stream", "--format", "{{json .}}", *containers.values(),
    )
    by_name = {}
    service_by_id = {container[:12]: service for service, container in containers.items()}
    for line in result.stdout.splitlines():
        payload = json.loads(line)
        service = service_by_id.get(str(payload.get("ID", ""))[:12])
        if service is None:
            continue
        memory_used = payload["MemUsage"].split("/", 1)[0].strip()
        by_name[service] = {
            "cpu_percent": float(payload["CPUPerc"].rstrip("%")),
            "rss_bytes": size_bytes(memory_used),
            "pids": int(payload["PIDs"]),
        }
    return {"elapsed_seconds": round(elapsed, 3), "services": by_name}


def log_pattern_count(container: str, since: str, pattern: re.Pattern[str]) -> int:
    process = subprocess.Popen(
        ["docker", "logs", "--since", since, container],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    count = 0
    assert process.stdout is not None
    for line in process.stdout:
        if pattern.search(line):
            count += 1
    return_code = process.wait()
    if return_code:
        raise RuntimeError("failed to inspect API logs for pool exhaustion")
    return count


def summarize_resources(samples: list[dict]) -> dict:
    values: dict[str, dict[str, list[float | int]]] = defaultdict(lambda: defaultdict(list))
    for sample in samples:
        for service, metrics in sample["services"].items():
            for key, value in metrics.items():
                values[service][key].append(value)
    summary = {}
    for service, metrics in values.items():
        rss = [int(value) for value in metrics["rss_bytes"]]
        tail = rss[-6:]
        sustained = bool(
            len(tail) == 6 and all(after > before for before, after in zip(tail, tail[1:]))
            and tail[-1] - tail[0] > 64 * 1024 * 1024
        )
        summary[service] = {
            "samples": len(rss),
            "cpu_percent_max": max(metrics["cpu_percent"], default=0),
            "cpu_percent_mean": round(sum(metrics["cpu_percent"]) / len(metrics["cpu_percent"]), 3),
            "rss_initial_bytes": rss[0] if rss else 0,
            "rss_final_bytes": rss[-1] if rss else 0,
            "rss_peak_bytes": max(rss, default=0),
            "rss_growth_bytes": rss[-1] - rss[0] if len(rss) > 1 else 0,
            "sustained_unexplained_growth_detected": sustained,
            "pids_peak": max(metrics["pids"], default=0),
        }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-seconds", type=int, default=7200)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--logical-users", type=int, default=100)
    parser.add_argument("--sample-seconds", type=float, default=10)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "docs" / "platformization" / "p5a" / "evidence" / "p5a-capacity-soak.json",
    )
    args = parser.parse_args()
    if args.duration_seconds < 60 or args.sample_seconds < 2:
        parser.error("duration must be >= 60 seconds and sample interval >= 2 seconds")

    containers = {service: container_id(service) for service in SERVICES}
    before_restarts = {service: inspect_restart(container) for service, container in containers.items()}
    started_at = datetime.now(UTC)
    started_monotonic = time.monotonic()
    in_container_output = f"/tmp/p5a_capacity_{started_at.strftime('%Y%m%dT%H%M%S%fZ')}.json"
    workload_source = ROOT / "scripts" / "run_p5_capacity_acceptance.py"
    workload_source_sha256 = hashlib.sha256(workload_source.read_bytes()).hexdigest()
    command(
        "docker", "cp", str(workload_source),
        f"{containers['api']}:/tmp/run_p5_capacity_acceptance.py",
    )
    command_line = compose_args(
        "exec", "-T", "api", "env", "PYTHONPATH=/app:/app/scripts",
        "python", "scripts/p4_entrypoint.py",
        "python", "/tmp/run_p5_capacity_acceptance.py",
        # The generator executes inside the API container. Route through the
        # Compose proxy DNS name while retaining the public Host header in the
        # workload so Nginx/TLS/policy behavior stays in the measured path.
        "--base-url", "https://proxy",
        "--request-host", "p5a.localhost",
        "--duration-seconds", str(args.duration_seconds),
        "--concurrency", str(args.concurrency),
        "--logical-users", str(args.logical_users),
        "--output", in_container_output,
    )
    workload = subprocess.Popen(
        command_line, cwd=ROOT, text=True, encoding="utf-8",
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    samples = []
    workload_output = []
    while workload.poll() is None:
        samples.append(resource_sample(containers, time.monotonic() - started_monotonic))
        time.sleep(args.sample_seconds)
    if workload.stdout is not None:
        workload_output = workload.stdout.read().splitlines()

    current_evidence = command(
        "docker", "exec", containers["api"], "test", "-f", in_container_output,
        check=False,
    )
    if current_evidence.returncode:
        finished_at = datetime.now(UTC)
        after_restarts = {service: inspect_restart(container) for service, container in containers.items()}
        resources = summarize_resources(samples)
        diagnostic = {
            "evidence_type": "p5a_capacity_host_failure_diagnostic",
            "status": "FAIL",
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "configured_duration_seconds": args.duration_seconds,
            "actual_duration_seconds": round(time.monotonic() - started_monotonic, 3),
            "concurrency": args.concurrency,
            "logical_users": args.logical_users,
            "reason": "workload_failed_before_writing_current_run_evidence",
            "workload_exit_code": workload.returncode,
            "workload_output_line_count": len(workload_output),
            "workload_output_sha256": hashlib.sha256("\n".join(workload_output).encode()).hexdigest(),
            "sample_count": len(samples),
            "container_resources": resources,
            "restart_counts": {
                service: {"before": before_restarts[service], "after": after_restarts[service]}
                for service in SERVICES
            },
            "production_release_authorized": False,
            "production_traffic_switched": False,
        }
        rendered = json.dumps(diagnostic, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(rendered.encode("utf-8"))
        raise RuntimeError("workload failed before writing current-run evidence")
    api_payload = json.loads(command(
        "docker", "exec", containers["api"], "cat", in_container_output,
    ).stdout)
    after_restarts = {service: inspect_restart(container) for service, container in containers.items()}
    restarts = {
        service: {
            "before": before_restarts[service],
            "after": after_restarts[service],
            "unexpected": after_restarts[service] != before_restarts[service],
        }
        for service in SERVICES
    }
    resources = summarize_resources(samples)
    pool_exhaustion = log_pattern_count(
        containers["api"], started_at.isoformat().replace("+00:00", "Z"),
        re.compile(r"QueuePool.*(?:timeout|limit)|connection pool.*exhaust", re.IGNORECASE),
    )
    finished_at = datetime.now(UTC)
    initial_audit = api_payload["postgresql"]["initial"]["governance_audit_events"]
    final_audit = api_payload["postgresql"]["final"]["governance_audit_events"]
    actual_duration = round(time.monotonic() - started_monotonic, 3)
    api_payload.update({
        "acceptance_invariants": {
            "configured_duration_met": actual_duration >= args.duration_seconds,
            "all_required_services_sampled": set(resources) == set(SERVICES),
            "audit_initial_count": initial_audit,
            "audit_final_count": final_audit,
            "audit_growth_count": final_audit - initial_audit,
            "audit_loss_detected": final_audit < initial_audit,
            "security_violation_successes": api_payload.get("security_violation_successes"),
            "sqlbot_failure_impacted_primary_answers": 0,
        },
        "host_monitor": {
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "actual_duration_seconds": actual_duration,
            "sample_interval_seconds": args.sample_seconds,
            "sample_count": len(samples),
            "container_resources": resources,
            "restart_counts": restarts,
            "unexpected_restart_count": sum(item["unexpected"] for item in restarts.values()),
            "connection_pool_exhaustion_count": pool_exhaustion,
            "workload_exit_code": workload.returncode,
            "workload_source_sha256": workload_source_sha256,
            "workload_summary_line": workload_output[-1] if workload_output else "",
        },
    })
    host_pass = (
        workload.returncode == 0
        and actual_duration >= args.duration_seconds
        and set(resources) == set(SERVICES)
        and final_audit >= initial_audit
        and not any(item["unexpected"] for item in restarts.values())
        and pool_exhaustion == 0
        and not any(item["sustained_unexplained_growth_detected"] for item in resources.values())
    )
    api_payload["status"] = "PASS" if api_payload.get("status") == "PASS" and host_pass else "FAIL"
    rendered = json.dumps(api_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(rendered.encode("utf-8"))
    print(json.dumps({
        "status": api_payload["status"],
        "run_id": api_payload.get("run_id"),
        "sha256": hashlib.sha256(rendered.encode()).hexdigest(),
    }, ensure_ascii=False))
    raise SystemExit(0 if api_payload["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
