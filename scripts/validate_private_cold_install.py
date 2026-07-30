"""Build and validate a private release candidate from an empty Compose project."""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from private_deployment import (
    DEFAULT_COMPOSE_FILE,
    DEFAULT_ENV_FILE,
    OperationError,
    PrivateDeployment,
    write_json,
)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compose-file", type=Path, default=DEFAULT_COMPOSE_FILE)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=420)
    parser.add_argument("--allow-self-signed", action="store_true")
    return parser.parse_args()


def parse_services(raw: str) -> list[dict]:
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        return [json.loads(line) for line in raw.splitlines() if line.strip()]


def main() -> int:
    args = parse_args()
    deployment = PrivateDeployment(args.compose_file, args.env_file, args.project_name)
    started = time.monotonic()
    try:
        preflight = deployment.preflight()
        before = deployment.run("ps", "--all", "--format", "json").stdout.strip()
        if before and parse_services(before):
            raise OperationError("cold-install project already contains containers")

        deployment.run("up", "-d", "--build", capture_output=False)
        service_status: dict[str, dict[str, str]] = {}
        while time.monotonic() - started < args.timeout_seconds:
            services = parse_services(deployment.run("ps", "--format", "json").stdout)
            service_status = {
                item.get("Service"): {
                    "state": item.get("State", ""),
                    "health": item.get("Health", ""),
                }
                for item in services
            }
            if len(service_status) == 4 and all(
                value["state"] == "running" and value["health"] in {"healthy", ""}
                for value in service_status.values()
            ):
                break
            time.sleep(3)
        else:
            raise OperationError("private services did not become healthy before timeout")

        context = (
            ssl._create_unverified_context()
            if args.allow_self_signed
            else ssl.create_default_context()
        )
        ready_url = deployment.env["PUBLIC_BASE_URL"].rstrip("/") + "/api/v1/health/ready"
        with urllib.request.urlopen(ready_url, timeout=10, context=context) as response:
            readiness = json.loads(response.read().decode("utf-8"))
        if readiness.get("status") != "ready":
            raise OperationError("HTTPS readiness endpoint did not report ready")

        http_port = deployment.env.get("HTTP_PORT", "80")
        public_host = deployment.env.get("PUBLIC_HOST", "localhost")
        redirect_url = f"http://{public_host}:{http_port}/api/v1/health"
        redirect_code = None
        redirect_location = None
        opener = urllib.request.build_opener(NoRedirect())
        try:
            opener.open(redirect_url, timeout=10)
        except urllib.error.HTTPError as exc:
            redirect_code = exc.code
            redirect_location = exc.headers.get("Location")
        if redirect_code != 308 or not (redirect_location or "").startswith("https://"):
            raise OperationError("HTTP endpoint did not enforce an HTTPS 308 redirect")

        user, database = deployment.database_identity()
        revision = deployment.psql(
            "SELECT version_num FROM alembic_version",
            user=user,
            database=database,
        )
        demo_users = int(
            deployment.psql(
                "SELECT count(*) FROM app_user",
                user=user,
                database=database,
            )
        )
        if revision != deployment.env.get("EXPECTED_DATABASE_REVISION", "0012"):
            raise OperationError("cold database revision does not match the release contract")
        if demo_users != 0:
            raise OperationError("production cold install unexpectedly created demo users")

        result = {
            "status": "passed",
            "executed_at": datetime.now(UTC).isoformat(),
            "project_name": args.project_name,
            "release_version": preflight["release_version"],
            "data_classification": "simulated",
            "services": service_status,
            "https_readiness": readiness,
            "http_redirect_code": redirect_code,
            "http_redirect_location_is_https": True,
            "database_revision": revision,
            "demo_users_created": demo_users,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "volumes_preserved": True,
            "production_claim": False,
        }
        write_json(args.output, result)
        return 0
    except Exception as exc:
        result = {
            "status": "failed",
            "executed_at": datetime.now(UTC).isoformat(),
            "project_name": args.project_name,
            "error_type": type(exc).__name__,
            "message": str(exc),
            "volumes_preserved": True,
        }
        write_json(args.output, result)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
