import json
import os
from datetime import date
from pathlib import Path

from app.core.database import SessionLocal
from app.models.sales import SalesOrder
from app.platform.identity import IdentityContext
from app.platform.scenario_packages import ScenarioRegistry
from app.scenarios.sales_ops.metrics import SALES_METRICS, SalesOpsMetricService

ROOT = Path(__file__).resolve().parents[1]
BASELINE = Path(os.getenv(
    "SALES_OPS_METRIC_BASELINE",
    ROOT / "tests" / "evaluation" / "sales_ops_metric_baseline_v1.json",
))


def main() -> None:
    expected = json.loads(BASELINE.read_text(encoding="utf-8"))
    with SessionLocal() as db:
        order = db.query(SalesOrder).first()
        if order is None:
            raise SystemExit("sales_ops simulated data is not installed")
        identity = IdentityContext(
            subject_id="acceptance:metric-reconciliation",
            tenant_id="tenant-alpha",
            org_id="org-alpha",
            workspace_id="workspace-alpha",
            roles=("analyst_admin",),
            groups=(),
            data_scopes=("workspace:all",),
            auth_strength="local-acceptance",
            issued_at=order.created_at,
            request_id="SALES-METRIC-RECONCILIATION",
        )
        release = ScenarioRegistry(db).resolve(identity, "sales_ops")
        actual = SalesOpsMetricService(db).calculate(
            date.fromisoformat(expected["period"]["start"]),
            date.fromisoformat(expected["period"]["end_exclusive"]),
        )
    differences = {
        metric_id: {
            "expected": expected["metrics"][metric_id],
            "actual": actual[metric_id],
        }
        for metric_id in SALES_METRICS
        if actual[metric_id] != expected["metrics"][metric_id]
    }
    result = {
        "status": "passed" if not differences else "failed",
        "scenario_id": release.scenario_id,
        "scenario_version": release.version,
        "data_classification": expected["data_classification"],
        "seed_run_id": expected["seed_run_id"],
        "metrics_checked": len(SALES_METRICS),
        "differences": differences,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if differences:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
