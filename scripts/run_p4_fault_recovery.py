"""Verify P4 Redis, PostgreSQL, and Vault fail-closed recovery behavior."""

from __future__ import annotations

import argparse
import json
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "deploy" / "preproduction" / "compose.yaml"
PROJECT = "renewable-p4-rc"
CONTAINERS = {
    "redis": "renewable-p4-rc-redis-1",
    "db": "renewable-p4-rc-db-1",
    "vault": "renewable-p4-rc-vault-1",
}


def command(*args: str, capture: bool = False) -> str:
    process = subprocess.run(
        list(args), cwd=ROOT, text=True, encoding="utf-8",
        capture_output=capture,
    )
    if process.returncode:
        if capture and process.stderr:
            print(process.stderr, end="")
        raise RuntimeError(f"command failed without destructive cleanup: {args[:3]}")
    return process.stdout.strip() if capture else ""


def compose(*args: str, capture: bool = False) -> str:
    return command(
        "docker", "compose", "-p", PROJECT, "-f", str(COMPOSE), *args,
        capture=capture,
    )


def ready_status() -> int:
    request = urllib.request.Request(
        "https://127.0.0.1:8444/api/v1/health/ready",
        headers={"Host": "p4.localhost"},
    )
    try:
        with urllib.request.urlopen(
            request, timeout=5, context=ssl._create_unverified_context(),
        ) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (OSError, TimeoutError):
        return 0


def wait_ready(expected: int, timeout: float = 90) -> float:
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        if ready_status() == expected:
            return round(time.monotonic() - started, 3)
        time.sleep(1)
    raise RuntimeError(f"readiness did not reach {expected}")


def restart_count(service: str) -> int:
    value = command(
        "docker", "inspect", CONTAINERS[service],
        "--format", "{{.RestartCount}}", capture=True,
    )
    return int(value)


def wait_health(service: str, timeout: float = 90) -> float:
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        template = (
            "{{.State.Status}}" if service == "vault"
            else "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}"
        )
        status = command(
            "docker", "inspect", CONTAINERS[service], "--format", template,
            capture=True,
        )
        expected = "running" if service == "vault" else "healthy"
        if status == expected:
            return round(time.monotonic() - started, 3)
        time.sleep(1)
    raise RuntimeError(f"{service} did not become healthy")


def exercise(service: str) -> dict:
    before = restart_count(service)
    compose("stop", service)
    fail_closed_seconds = wait_ready(503)
    compose("start", service)
    healthy_seconds = wait_health(service)
    if service == "vault":
        fail_closed = compose(
            "exec", "-T", "api", "python", "scripts/p4_entrypoint.py",
            "python", "scripts/verify_p4_secret_fail_closed.py", capture=True,
        )
        fail_closed_payload = json.loads(fail_closed.splitlines()[-1])
        compose("run", "--rm", "vault-bootstrap")
    else:
        fail_closed_payload = None
    recovered_seconds = wait_ready(200)
    after = restart_count(service)
    return {
        "readiness_failed_closed": True,
        "fail_closed_seconds": fail_closed_seconds,
        "container_healthy_seconds": healthy_seconds,
        "readiness_recovered_seconds": recovered_seconds,
        "restart_count_before": before,
        "restart_count_after": after,
        "unexpected_restart": after != before,
        "secret_resolution": fail_closed_payload,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if ready_status() != 200:
        raise SystemExit("P4 readiness must be healthy before fault injection")
    result = {
        "status": "PASS",
        "environment": "preproduction",
        "data_classification": "simulated",
        "volumes_deleted": False,
        "secret_values_printed": False,
        "services": {},
    }
    for service in ("redis", "db", "vault"):
        result["services"][service] = exercise(service)
    if any(item["unexpected_restart"] for item in result["services"].values()):
        result["status"] = "FAIL"
    rendered = json.dumps(result, ensure_ascii=False, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    raise SystemExit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
