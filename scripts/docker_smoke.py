import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:18000/api/v1"
ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    checks = {}
    with httpx.Client(timeout=120, trust_env=False) as client:
        health = client.get(f"{BASE}/health"); health.raise_for_status()
        checks["health"] = health.json()["status"] == "ok"
        login = client.post(f"{BASE}/auth/login", json={"username": "analyst", "password": "AlphaAnalyst!2026"}); login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
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
        denied = client.post(f"{BASE}/auth/login", json={"username": "regional", "password": "AlphaRegion!2026"}); denied.raise_for_status()
        regional_headers = {"Authorization": f"Bearer {denied.json()['access_token']}"}
        forbidden = client.post(f"{BASE}/chat/query", headers=regional_headers, json={"question": "区域B在2026年6月充电收入是多少？"})
        checks["regional_scope_403"] = forbidden.status_code == 403
    report = {"executed_at": datetime.now(timezone.utc).isoformat(), "base_url": BASE, "checks": checks, "passed": all(checks.values())}
    output = ROOT / "tests" / "evaluation" / "output" / "docker_smoke.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
