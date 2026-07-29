import json
import os
from datetime import date
from pathlib import Path

from app.core.database import SessionLocal
from app.scenarios.charging_ops.manifest import METRICS
from app.scenarios.registry import published_charging_ops
from app.services.metrics import MetricService

ROOT = Path(__file__).resolve().parents[1]
BASELINE = Path(os.getenv(
    "P0_5_METRIC_BASELINE",
    ROOT / "docs" / "v2" / "evidence" / "p0_5" / "metric_baseline_before_scenario.json",
))


def main() -> None:
    expected = json.loads(BASELINE.read_text(encoding="utf-8"))
    with SessionLocal() as db:
        release = published_charging_ops(db)
        if release is None:
            raise SystemExit("charging_ops scenario is not published")
        actual = MetricService(db).compute(
            list(METRICS),
            date.fromisoformat(expected["period"]["start"]),
            date.fromisoformat(expected["period"]["end_exclusive"]),
        )
    differences = {
        metric_id: {"expected": expected["metrics"][metric_id], "actual": actual[metric_id]}
        for metric_id in METRICS
        if actual[metric_id] != expected["metrics"][metric_id]
    }
    result = {
        "status": "passed" if not differences else "failed",
        "scenario_id": release.scenario_id,
        "scenario_version": release.version,
        "source_batch_id": release.source_batch_id,
        "metrics_checked": len(METRICS),
        "differences": differences,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if differences:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
