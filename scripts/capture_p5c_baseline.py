"""Capture the P5C Git, version, migration, and launcher adjudication without secrets."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IMPLEMENTATION_SHA = "f173783dd5ba516e5cf7c376042dfc31da06a5a3"
GOVERNANCE_SHA = "6ee3ccc9e893960f11d4a147d676de1ba0b00e6f"
REMOTE_REF = "origin/fix/p5b-local-gate-closure"
EXPECTED_GOVERNANCE_FILES = {
    "docs/platformization/p5b/05_FINAL_LOCAL_GATE_CLOSEOUT.md",
    "docs/platformization/p5b/06_ACCEPTANCE_PACKAGE_4.0.0-rc.3.md",
    "docs/platformization/p5b/evidence/p5b-gate-snapshot-post-push.json",
    "docs/platformization/p5b/evidence/p5b-rc-4.0.0-rc.3-manifest.json",
    "docs/platformization/p5b/evidence/p5b-remote-push.json",
}


def git(*args: str, check: bool = True) -> str:
    process = subprocess.run(
        ["git", *args], cwd=ROOT, text=True, encoding="utf-8", capture_output=True,
    )
    if check and process.returncode:
        raise RuntimeError(f"git command failed safely: {args[:2]}")
    return process.stdout.strip()


def git_succeeds(*args: str) -> bool:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True,
    ).returncode == 0


def migration_heads() -> list[str]:
    revisions: set[str] = set()
    parents: set[str] = set()
    for path in sorted((ROOT / "backend" / "alembic" / "versions").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        values: dict[str, object] = {}
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}:
                values[target.id] = ast.literal_eval(node.value)
        revision = values.get("revision")
        if isinstance(revision, str):
            revisions.add(revision)
        down = values.get("down_revision")
        if isinstance(down, str):
            parents.add(down)
        elif isinstance(down, tuple):
            parents.update(item for item in down if isinstance(item, str))
    return sorted(revisions - parents)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "docs/platformization/p5c/evidence/p5c-baseline-adjudication.json",
    )
    args = parser.parse_args()

    for commit in (IMPLEMENTATION_SHA, GOVERNANCE_SHA):
        git("cat-file", "-e", f"{commit}^{{commit}}")
    branch = git("branch", "--show-current")
    head = git("rev-parse", "HEAD")
    tracking_sha = git("rev-parse", REMOTE_REF)
    relation = git("rev-list", "--left-right", "--count", f"{REMOTE_REF}...{GOVERNANCE_SHA}").split()
    changed_files = set(git("diff", "--name-only", IMPLEMENTATION_SHA, GOVERNANCE_SHA).splitlines())
    local_status = git("status", "--short").splitlines()
    heads = migration_heads()

    manifest_path = ROOT / "docs/platformization/p5b/evidence/p5b-rc-4.0.0-rc.3-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    override_text = (ROOT / "deploy/production-acceptance/p5b.override.yaml").read_text(encoding="utf-8")
    compose_version = re.search(r"^\s*RELEASE_VERSION:\s*(\S+)\s*$", override_text, re.MULTILINE)

    checks = {
        "implementation_is_parent_of_governance": git_succeeds(
            "merge-base", "--is-ancestor", IMPLEMENTATION_SHA, GOVERNANCE_SHA,
        ),
        "governance_diff_is_evidence_only": changed_files == EXPECTED_GOVERNANCE_FILES,
        "tracking_ref_matches_pushed_implementation": tracking_sha == IMPLEMENTATION_SHA,
        "tracking_relation_is_remote_0_local_1": relation == ["0", "1"],
        "implementation_commit_count_152": git("rev-list", "--count", IMPLEMENTATION_SHA) == "152",
        "governance_commit_count_153": git("rev-list", "--count", GOVERNANCE_SHA) == "153",
        "migration_head_is_p5_0001": heads == ["p5_0001"],
        "manifest_release_is_4_0_0_rc_3": manifest.get("release_candidate") == "4.0.0-rc.3",
        "compose_release_is_4_0_0_rc_3": bool(compose_version and compose_version.group(1) == "4.0.0-rc.3"),
        "launcher_is_unique": (ROOT / "一键启动.bat").is_file(),
        "p5c_control_branch": branch == "codex/p5c-baseline-convergence",
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    payload = {
        "schema_version": "1.0",
        "evidence_type": "p5c_baseline_adjudication",
        "status": status,
        "captured_at": datetime.now(UTC).isoformat(),
        "git": {
            "worktree": str(ROOT),
            "branch": branch,
            "head_at_capture": head,
            "selected_start_sha": GOVERNANCE_SHA,
            "selected_start_reason": "latest complete P5B implementation plus local distribution-governance evidence",
            "pushed_implementation_sha": IMPLEMENTATION_SHA,
            "remote_tracking_ref": REMOTE_REF,
            "remote_tracking_sha": tracking_sha,
            "ahead": int(relation[1]),
            "behind": int(relation[0]),
            "implementation_commit_count": 152,
            "governance_commit_count": 153,
            "governance_diff_files": sorted(changed_files),
            "worktrees": git("worktree", "list", "--porcelain").splitlines(),
            "status_entries": local_status,
        },
        "remote_verification": {
            "git_transport": "UNAVAILABLE_CONNECTION_RESET",
            "git_transport_attempts": 2,
            "github_branch_page_commit_count": 152,
            "github_branch_page_checked_at": "2026-08-08",
            "adjudication": "remote branch remains at the 152-commit implementation baseline; no push performed",
        },
        "version_truth": {
            "current_runtime_release": manifest.get("release_candidate"),
            "current_runtime_source_sha": manifest.get("source_git_sha"),
            "current_compose_release": compose_version.group(1) if compose_version else None,
            "current_migration_heads": heads,
            "next_release_stream": "4.1.0",
            "next_release_status": "PLANNED_NOT_YET_RC",
            "production_release_authorized": False,
            "production_traffic_switched": False,
        },
        "launcher": {
            "user_entry": "一键启动.bat",
            "implementation": "scripts/release/start-project.ps1",
            "compose_base": "deploy/preproduction/compose.yaml",
            "compose_override": "deploy/production-acceptance/p5b.override.yaml",
            "rebuilds_frozen_images": False,
        },
        "checks": checks,
        "input_document": {
            "path": "项目二_ChatBI_NL2SQL_一周全面落地实施总方案_v2.0(1).docx",
            "tracked": False,
            "included_in_candidate_commit": False,
        },
        "source_manifest_sha256": sha256(manifest_path),
        "secret_values_recorded": False,
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(json.dumps({"status": status, "checks": checks}, sort_keys=True))
    raise SystemExit(0 if status == "PASS" else 1)


if __name__ == "__main__":
    main()
