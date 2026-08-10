"""Bind the final SQLBot 4.1C2 acceptance summary to the post-closeout scan."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "platformization" / "sqlbot41" / "evidence"


def main() -> None:
    source = EVIDENCE / "sqlbot41c2-final-acceptance-summary-pre-postscan.json"
    scan_path = EVIDENCE / "secret-scan-post-closeout.json"
    output = EVIDENCE / "sqlbot41c2-final-acceptance-summary.json"
    if output.exists():
        raise RuntimeError(f"refusing to overwrite final evidence: {output}")
    summary = json.loads(source.read_text(encoding="utf-8"))
    scan = json.loads(scan_path.read_text(encoding="utf-8"))
    passed = scan.get("status") == "PASS" and scan.get("new_leakage_finding_count") == 0
    summary["checks"]["secret_scan"] = passed
    summary["post_closeout_secret_scan"] = {
        "status": scan.get("status"),
        "new_leakage_finding_count": scan.get("new_leakage_finding_count"),
        "sha256": hashlib.sha256(scan_path.read_bytes()).hexdigest(),
    }
    summary["artifacts"][scan_path.name] = {
        "sha256": hashlib.sha256(scan_path.read_bytes()).hexdigest(),
        "size": scan_path.stat().st_size,
    }
    summary["status"] = "PASS" if all(summary["checks"].values()) else "PARTIAL"
    summary["integration_allowed"] = summary["status"] == "PASS"
    output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": summary["status"], "post_closeout_secret_scan": passed}))
    if summary["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
