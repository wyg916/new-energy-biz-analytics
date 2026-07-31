import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.evaluation.live_model_provider_validation import (
    load_provider_specs,
    validate_all_providers,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Validate the approved Kimi, MiMo, and DeepSeek runtime contracts. "
            "Credentials must be injected through the current process only."
        )
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--timeout-probe-seconds", type=float, default=0.001)
    args = parser.parse_args()

    report = validate_all_providers(
        load_provider_specs(),
        timeout_seconds=args.timeout_seconds,
        timeout_probe_seconds=args.timeout_probe_seconds,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0 if report["usable_provider_count"] > 0 else 2)


if __name__ == "__main__":
    main()
