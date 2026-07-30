import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.evaluation.dual_engine_golden import evaluate_golden_contract


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Validate the P1B dual-engine Golden Set contract. This command "
            "does not claim SQLBot runtime execution accuracy."
        )
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=ROOT / "tests" / "evaluation" / "nl2sql_dual_engine_v1.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help=(
            "Optional evidence directory. Omit for a side-effect-free "
            "verification run."
        ),
    )
    args = parser.parse_args()

    source = json.loads(args.source.read_text(encoding="utf-8"))
    report = evaluate_golden_contract(source)
    report["evaluated_at"] = datetime.now(UTC).isoformat()
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = args.output_dir / "dual_engine_golden_contract_v1.json"
        output_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    summary = {
        key: report[key]
        for key in (
            "contract_status",
            "total",
            "passed",
            "failed",
            "failed_ids",
            "category_counts",
            "scenario_counts",
            "security_candidates",
            "dangerous_sql_successes",
            "permission_attack_successes",
            "runtime_evaluation",
            "canary_eligible",
            "canary_blockers",
        )
    }
    print(json.dumps(summary, ensure_ascii=False))
    raise SystemExit(0 if report["contract_status"] == "PASS" else 1)


if __name__ == "__main__":
    main()

