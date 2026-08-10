"""Negative checks for the fail-closed SQLBot readonly verification wrapper."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "Verify-SQLBot41CReadonly.ps1"


def _run(*arguments: str) -> dict[str, object]:
    output = f"docs/platformization/sqlbot41/evidence/wrapper-negative-{uuid4().hex}.json"
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(WRAPPER),
            *arguments,
            "-Output",
            output,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    return {
        "exit_code": completed.returncode,
        "output": (completed.stdout or "") + (completed.stderr or ""),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    cases = {
        "missing_image": (
            ["-PlatformApiImage", "sqlbot41c-intentionally-missing:image"],
            "SQLBOT41C_IMAGE_NOT_FOUND",
        ),
        "missing_network": (
            ["-PlatformNetwork", "sqlbot41c-intentionally-missing-network"],
            "SQLBOT41C_NETWORK_NOT_FOUND",
        ),
        "missing_volume": (
            ["-RuntimeVolume", "sqlbot41c-intentionally-missing-volume"],
            "SQLBOT41C_VOLUME_NOT_FOUND",
        ),
        "missing_database": (
            ["-PlatformDatabaseContainer", "sqlbot41c-intentionally-missing-db"],
            "SQLBOT41C_DATABASE_UNAVAILABLE",
        ),
    }
    results = []
    for name, (arguments, expected_code) in cases.items():
        result = _run(*arguments)
        output = str(result["output"])
        passed = int(result["exit_code"]) != 0 and expected_code in output
        results.append({
            "case": name,
            "status": "PASS" if passed else "FAIL",
            "exit_code_nonzero": int(result["exit_code"]) != 0,
            "expected_error_code": expected_code,
            "implicit_pull_attempted": "Pulling from" in output or "latest:" in output,
        })
    report = {
        "status": "PASS" if all(item["status"] == "PASS" for item in results) else "FAIL",
        "total": len(results),
        "passed": sum(item["status"] == "PASS" for item in results),
        "results": results,
    }
    if args.output is not None:
        output_path = args.output.resolve()
        output_path.relative_to(ROOT)
        if output_path.exists():
            raise RuntimeError(f"refusing to overwrite evidence: {output_path}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
