"""Fail closed when frontend source introduces fabricated business-data paths."""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "frontend" / "src"
PATTERNS = {
    "runtime_random": re.compile(r"Math\.random\s*\("),
    "mock_or_fixture_import": re.compile(
        r"(?:from\s+|import\s*\(|require\s*\()[^\n]*(?:mock|fixture)", re.IGNORECASE
    ),
    "static_json_import": re.compile(
        r"(?:from\s+|import\s*\(|require\s*\()[^\n]*\.json(?:['\"]|\))", re.IGNORECASE
    ),
    "numeric_api_fallback": re.compile(
        r"catch\s*(?:\([^)]*\))?\s*\{[^}]{0,400}(?:return|set\w+)\s*\(?(?:\d+(?:\.\d+)?|\[[^\]]*\d)",
        re.IGNORECASE | re.DOTALL,
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    findings: list[dict] = []
    scanned_files = 0
    for path in sorted(SOURCE.rglob("*")):
        if path.suffix not in {".ts", ".tsx", ".js", ".jsx"}:
            continue
        scanned_files += 1
        text = path.read_text(encoding="utf-8")
        for rule, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                findings.append({
                    "rule": rule,
                    "path": path.relative_to(ROOT).as_posix(),
                    "line": text.count("\n", 0, match.start()) + 1,
                })
    payload = {
        "evidence_type": "data41_frontend_business_data_truth_scan",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_root": "frontend/src",
        "scanned_files": scanned_files,
        "rules": sorted(PATTERNS),
        "findings": findings,
        "finding_count": len(findings),
        "status": "PASS" if not findings else "FAIL",
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "finding_count": len(findings)}))
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
