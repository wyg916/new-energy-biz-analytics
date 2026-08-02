import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE = os.getenv("DOCKER_SMOKE_BASE", "http://127.0.0.1:18000/api/v1")
HOST_HEADER = os.getenv("DOCKER_SMOKE_HOST_HEADER")


def oidc_access_token(container: str, username: str) -> str:
    """Create an acceptance-only server session without exposing its token."""
    script = (
        "import sys; "
        "sys.path.insert(0, '/app/scripts'); "
        "from run_p4_capacity_soak import token_for; "
        f"print(token_for({username!r})[0])"
    )
    process = subprocess.run(
        [
            "docker", "exec", container, "python", "scripts/p4_entrypoint.py",
            "python", "-c", script,
        ],
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    if process.returncode:
        raise RuntimeError(
            f"OIDC acceptance token creation failed for {username!r}; "
            "secret output was suppressed"
        )
    lines = process.stdout.strip().splitlines()
    if not lines:
        raise RuntimeError(f"OIDC acceptance token was empty for {username!r}")
    return lines[-1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run side-effect-free Docker smoke checks.")
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional evidence JSON path. Omit for a side-effect-free verification run.",
    )
    parser.add_argument(
        "--oidc-container",
        help=(
            "API container used to create server-side acceptance OIDC sessions. "
            "When set, local username/password login is not used."
        ),
    )
    parser.add_argument(
        "--server-oidc",
        action="store_true",
        help="Create acceptance OIDC sessions in the current API process context.",
    )
    parser.add_argument(
        "--regional-local-guard",
        action="store_true",
        help=(
            "Use the existing disabled-login regional principal only for the "
            "negative region-scope guard check."
        ),
    )
    parser.add_argument(
        "--insecure-tls",
        action="store_true",
        help="Allow the checked local acceptance stack's self-signed TLS certificate.",
    )
    args = parser.parse_args()
    if args.oidc_container and args.server_oidc:
        parser.error("choose only one OIDC session source")

    def acceptance_token(username: str) -> str:
        if username == "regional" and args.regional_local_guard:
            sys.path.insert(0, "/app/scripts")
            from sqlalchemy import select

            from app.core.database import SessionLocal
            from app.core.security import create_access_token
            from app.governance.models import Principal
            from app.models.auth import User

            with SessionLocal() as db:
                user = db.scalar(select(User).where(User.username == username))
                principal = db.scalar(
                    select(Principal).where(
                        Principal.local_user_id == user.id,
                        Principal.provider_code == "LOCAL",
                        Principal.status == "ACTIVE",
                    )
                ) if user else None
                if user is None or principal is None:
                    raise RuntimeError("regional negative-test principal is unavailable")
                return create_access_token(
                    user.id,
                    user.role,
                    auth_provider="LOCAL",
                    principal_id=principal.principal_id,
                )
        if args.server_oidc:
            sys.path.insert(0, "/app/scripts")
            from run_p4_capacity_soak import token_for

            return token_for(username)[0]
        if args.oidc_container:
            return oidc_access_token(args.oidc_container, username)
        raise RuntimeError("an acceptance OIDC session source is required")

    checks = {}
    client_headers = {"Host": HOST_HEADER} if HOST_HEADER else {}
    with httpx.Client(
        timeout=120,
        trust_env=False,
        headers=client_headers,
        verify=not args.insecure_tls,
    ) as client:
        health = client.get(f"{BASE}/health"); health.raise_for_status()
        checks["health"] = health.json()["status"] == "ok"
        if args.oidc_container or args.server_oidc:
            analyst_token = acceptance_token("analyst")
        else:
            login = client.post(
                f"{BASE}/auth/login",
                json={"username": "analyst", "password": "AlphaAnalyst!2026"},
            )
            login.raise_for_status()
            analyst_token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {analyst_token}"}
        query = "start=2026-06-01&end_exclusive=2026-07-01"
        dashboard = client.get(f"{BASE}/dashboard/summary?{query}", headers=headers); dashboard.raise_for_status()
        dashboard_body = dashboard.json()
        checks["dashboard_15_metrics"] = len(dashboard_body["metrics"]) == 15 and dashboard_body["metadata"]["source"] == "platform_database"
        chat = client.post(f"{BASE}/chat/query", headers=headers, json={"question": "区域A在2026年6月充电收入和毛利率是多少？"}); chat.raise_for_status()
        chat_body = chat.json()
        checks["chatbi_guarded"] = chat_body["status"] == "completed" and chat_body["evidence"]["query_guard"] == "passed" and chat_body["evidence"]["answer_guard"]["status"] == "passed"
        diagnostics = client.get(f"{BASE}/diagnostics/decomposition?metric=gross_profit&comparison=mom&limit=5&{query}", headers=headers); diagnostics.raise_for_status()
        diagnostics_body = diagnostics.json()
        checks["diagnostic_reconciled"] = abs(diagnostics_body["reconciliation"]["residual"]) <= 0.02
        report = client.get(f"{BASE}/reports/draft?report_type=monthly&{query}", headers=headers); report.raise_for_status()
        report_body = report.json()
        checks["report_traceable"] = report_body["metadata"]["analysis_run_id"] in report_body["markdown"] and report_body["metadata"]["data_classification"] == "simulated"
        if args.oidc_container or args.server_oidc:
            regional_token = acceptance_token("regional")
        else:
            denied = client.post(
                f"{BASE}/auth/login",
                json={"username": "regional", "password": "AlphaRegion!2026"},
            )
            denied.raise_for_status()
            regional_token = denied.json()["access_token"]
        regional_headers = {"Authorization": f"Bearer {regional_token}"}
        forbidden = client.post(f"{BASE}/chat/query", headers=regional_headers, json={"question": "区域B在2026年6月充电收入是多少？"})
        checks["regional_scope_denied"] = forbidden.status_code in {401, 403}
        regional_denial_status = forbidden.status_code
    report = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "base_url": BASE,
        "authentication": {
            "positive_checks": "server_oidc" if args.server_oidc else (
                "container_oidc" if args.oidc_container else "local_login"
            ),
            "regional_negative_check": (
                "existing_local_principal_with_login_disabled"
                if args.regional_local_guard else "same_as_positive_checks"
            ),
        },
        "regional_denial_http_status": regional_denial_status,
        "checks": checks,
        "passed": all(checks.values()),
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
