"""Scan a release worktree for committed-candidate secrets without reading .env files."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRIVY_IMAGE = "aquasec/trivy:0.70.0"
TRIVY_CACHE = "renewable-p5a-remediation_trivy_cache"
DEFAULT_OUTPUT = (
    ROOT / "docs" / "platformization" / "p5a" / "evidence" / "p5a-secret-scan.json"
)
DEFAULT_BASELINE = "cf37a43c444515f2c92530aab050410efac4b544"
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def command(*args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    process = subprocess.run(list(args), cwd=ROOT, capture_output=True)
    if check and process.returncode:
        raise RuntimeError(f"secret scan command failed safely: {args[:3]}")
    return process


def added_lines(baseline: str) -> tuple[dict[str, set[int] | None], str]:
    command("git", "cat-file", "-e", f"{baseline}^{{commit}}")
    diff = command(
        "git", "diff", "--no-ext-diff", "--no-color", "--unified=0", baseline, "--",
    ).stdout.decode("utf-8", errors="replace")
    candidates: dict[str, set[int] | None] = {}
    current: str | None = None
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
            candidates.setdefault(current, set())
            continue
        match = HUNK.match(line)
        if current is None or match is None:
            continue
        start = int(match.group(1))
        count = int(match.group(2) or "1")
        assert isinstance(candidates[current], set)
        candidates[current].update(range(start, start + count))
    untracked = command("git", "ls-files", "--others", "--exclude-standard").stdout.decode(
        "utf-8", errors="replace",
    )
    for path in untracked.splitlines():
        if path and not Path(path).name.startswith(".env"):
            candidates[path.replace("\\", "/")] = None
    return candidates, hashlib.sha256(diff.encode("utf-8")).hexdigest()


def normalized_target(target: object) -> str:
    value = str(target or "").replace("\\", "/")
    for prefix in ("/src/", "src/", "./"):
        if value.startswith(prefix):
            return value[len(prefix):]
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--baseline", default=DEFAULT_BASELINE)
    parser.add_argument("--scope", default="P5A")
    parser.add_argument("--cache-volume", default=TRIVY_CACHE)
    args = parser.parse_args()

    tracked = command("git", "ls-files", "--", ".env", ".env.*", "**/.env", "**/.env.*")
    tracked_env_names = [line for line in tracked.stdout.decode("utf-8").splitlines() if line]
    tracked_env_templates = [
        path for path in tracked_env_names
        if Path(path).name in {".env.example", ".env.sample", ".env.template"}
    ]
    forbidden_tracked_env_names = sorted(set(tracked_env_names) - set(tracked_env_templates))
    if forbidden_tracked_env_names:
        raise RuntimeError("tracked .env-style files are forbidden; contents were not read")
    candidate_lines, diff_sha256 = added_lines(args.baseline)

    command("docker", "volume", "create", args.cache_volume)
    version = command("docker", "run", "--rm", TRIVY_IMAGE, "--version")
    scan = command(
        "docker", "run", "--rm",
        "-v", f"{ROOT}:/src:ro",
        "-v", f"{args.cache_volume}:/root/.cache/trivy",
        TRIVY_IMAGE,
        "fs", "--scanners", "secret", "--skip-version-check", "--format", "json",
        "--skip-dirs", "/src/.git",
        "--skip-dirs", "/src/node_modules",
        "--skip-dirs", "/src/frontend/node_modules",
        "--skip-files", "**/.env*",
        "/src",
    )
    raw = json.loads(scan.stdout.decode("utf-8"))
    findings = []
    for result in raw.get("Results") or []:
        for secret in result.get("Secrets") or []:
            target = normalized_target(result.get("Target"))
            start_line = int(secret.get("StartLine") or 0)
            end_line = int(secret.get("EndLine") or start_line)
            lines = candidate_lines.get(target, "absent")
            is_new = lines is None or (
                isinstance(lines, set)
                and any(line in lines for line in range(start_line, end_line + 1))
            )
            findings.append({
                "target": target,
                "rule_id": secret.get("RuleID"),
                "category": secret.get("Category"),
                "severity": secret.get("Severity"),
                "title": secret.get("Title"),
                "start_line": start_line,
                "end_line": end_line,
                "introduced_after_baseline": is_new,
            })
    new_findings = [item for item in findings if item["introduced_after_baseline"]]
    payload = {
        "evidence_type": f"{args.scope.lower()}_sensitive_information_scan",
        "status": "PASS" if not new_findings else "BLOCKED",
        "scanned_at": datetime.now(UTC).isoformat(),
        "scope": f"{args.scope} worktree excluding forbidden .env-style files, Git internals, and dependency trees",
        "tracked_env_file_count": len(tracked_env_names),
        "tracked_env_template_count": len(tracked_env_templates),
        "forbidden_tracked_env_file_count": 0,
        "env_file_contents_read": False,
        "ignored_findings": 0,
        "baseline_commit": args.baseline,
        "candidate_diff_sha256": diff_sha256,
        "scanner_image": TRIVY_IMAGE,
        "scanner_version": version.stdout.decode("utf-8", errors="replace").strip(),
        "raw_result_sha256": hashlib.sha256(scan.stdout).hexdigest(),
        "total_worktree_finding_count": len(findings),
        "pre_existing_finding_count": len(findings) - len(new_findings),
        "new_leakage_finding_count": len(new_findings),
        "new_findings_without_secret_values": new_findings,
        "secret_values_recorded": False,
        "production_release_authorized": False,
        "production_traffic_switched": False,
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(rendered.encode("utf-8"))
    print(json.dumps({
        "status": payload["status"],
        "total_worktree_finding_count": len(findings),
        "new_leakage_finding_count": len(new_findings),
        "evidence_sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
    }, sort_keys=True))
    raise SystemExit(0 if not new_findings else 1)


if __name__ == "__main__":
    main()
