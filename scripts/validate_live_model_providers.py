import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.evaluation.official_model_provider_validation import (
    load_provider_specs,
    parse_env_file,
    validate_all_providers,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Validate Kimi, DeepSeek, and MiMo using their distinct official "
            "runtime contracts without exposing credential values."
        )
    )
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args()

    env_audit = None
    if args.env_file:
        values, env_audit = parse_env_file(args.env_file)
        specs = load_provider_specs(values)
    else:
        specs = load_provider_specs()
    report = validate_all_providers(
        specs,
        timeout_seconds=args.timeout_seconds,
        env_audit=env_audit,
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
