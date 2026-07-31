import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.evaluation.runtime_closeout import (
    ModelContractPresence,
    build_blocked_runtime_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Record fail-closed P2A runtime evidence when a complete live "
            "model contract is unavailable. This command makes no external "
            "requests and must not be counted as runtime execution."
        )
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=ROOT / "tests" / "evaluation" / "nl2sql_dual_engine_v1.json",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--provider-present", action="store_true")
    parser.add_argument("--base-url-present", action="store_true")
    parser.add_argument("--model-name-present", action="store_true")
    parser.add_argument("--credential-ref-present", action="store_true")
    parser.add_argument(
        "--runtime-blocker",
        choices=(
            "HUMAN_MODEL_CONFIG_REQUIRED",
            "LIVE_EXECUTION_REQUIRED",
            "PROVIDER_AUTHENTICATION_FAILED",
        ),
    )
    parser.add_argument("--charging-min-date", default="2025-01-01")
    parser.add_argument("--charging-max-date", default="2026-06-30")
    parser.add_argument("--sales-min-date", default="2025-01-01")
    parser.add_argument("--sales-max-date", default="2026-06-30")
    args = parser.parse_args()

    source = json.loads(args.source.read_text(encoding="utf-8"))
    contract = ModelContractPresence(
        provider=args.provider_present,
        base_url=args.base_url_present,
        model_name=args.model_name_present,
        credential_ref=args.credential_ref_present,
    )
    report = build_blocked_runtime_report(
        source,
        model_contract=contract,
        runtime_blocker=args.runtime_blocker,
        charging_min_date=args.charging_min_date,
        charging_max_date=args.charging_max_date,
        sales_min_date=args.sales_min_date,
        sales_max_date=args.sales_max_date,
    )
    report["recorded_at"] = datetime.now(UTC).isoformat()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print(json.dumps({
        "runtime_status": report["runtime_status"],
        "model_contract": report["model_contract"],
        "model_called": report["model_called"],
        "external_request_count": report["external_request_count"],
        "smoke": {
            key: report["smoke"][key]
            for key in ("status", "total", "executed", "not_executed")
        },
        "golden": {
            key: report["golden"][key]
            for key in ("status", "total", "executed", "not_executed")
        },
        "shadow": report["shadow"],
        "canary": report["canary"],
    }, ensure_ascii=False))
    raise SystemExit(2)


if __name__ == "__main__":
    main()
