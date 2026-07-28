"""Collect sanitized, machine-readable V2-P0.0 runtime evidence."""

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "v2" / "evidence" / "alpha"
API_DIR = EVIDENCE / "api"


def run(*args: str) -> str:
    process = subprocess.run(
        list(args),
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return process.stdout.strip()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    collected_at = datetime.now(UTC).isoformat()
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    API_DIR.mkdir(parents=True, exist_ok=True)

    tag_target = run("git", "rev-list", "-n", "1", "alpha-v1.0.0")
    git_evidence = {
        "collected_at": collected_at,
        "branch": run("git", "branch", "--show-current"),
        "head": run("git", "rev-parse", "HEAD"),
        "alpha_acceptance_commit": "1f580b6c251c0f20d4ed6927b4b60252b7deba8d",
        "post_acceptance_startup_commit": "1f6f2dc47bf99f4ecbb34d636b5efd5831a97d33",
        "alpha_tag": "alpha-v1.0.0",
        "alpha_tag_target": tag_target,
        "remote": run("git", "remote", "get-url", "origin"),
        "working_tree_during_evidence_collection": run("git", "status", "--porcelain"),
    }
    write_json(EVIDENCE / "git_baseline.json", git_evidence)

    services = []
    for line in run("docker", "compose", "ps", "--format", "json").splitlines():
        item = json.loads(line)
        services.append(
            {
                "service": item.get("Service"),
                "name": item.get("Name"),
                "image": item.get("Image"),
                "state": item.get("State"),
                "health": item.get("Health") or "not_configured",
                "status": item.get("Status"),
                "ports": item.get("Ports"),
            }
        )
    write_json(
        EVIDENCE / "docker_compose_status.json",
        {"collected_at": collected_at, "services": services},
    )

    with urlopen("http://127.0.0.1:18000/api/v1/health", timeout=10) as response:
        api_health = json.loads(response.read())
        api_status = response.status
    with urlopen("http://127.0.0.1:8080", timeout=10) as response:
        web_status = response.status
        web_bytes = len(response.read())
    write_json(
        EVIDENCE / "health_status.json",
        {
            "collected_at": collected_at,
            "api_http_status": api_status,
            "api": api_health,
            "web_http_status": web_status,
            "web_response_bytes": web_bytes,
        },
    )

    current_revision = run("docker", "compose", "exec", "-T", "api", "alembic", "current")
    head_revision = run("docker", "compose", "exec", "-T", "api", "alembic", "heads")
    write_json(
        EVIDENCE / "alembic_status.json",
        {
            "collected_at": collected_at,
            "current": current_revision,
            "head": head_revision,
        },
    )

    write_json(
        EVIDENCE / "environment_versions.json",
        {
            "collected_at": collected_at,
            "python": sys.version.split()[0],
            "node": run("node", "--version"),
            "npm": run("npm.cmd", "--version"),
            "docker": run("docker", "--version"),
            "docker_compose": run("docker", "compose", "version"),
            "git": run("git", "--version"),
            "github_cli": run("gh", "--version").splitlines()[0],
            "os": "Windows",
        },
    )

    with urlopen("http://127.0.0.1:18000/openapi.json", timeout=30) as response:
        openapi = json.loads(response.read())
    openapi_bytes = (
        json.dumps(openapi, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    )
    openapi_path = API_DIR / "openapi.json"
    openapi_path.write_bytes(openapi_bytes)
    write_json(
        API_DIR / "openapi.sha256.json",
        {
            "collected_at": collected_at,
            "algorithm": "sha256",
            "file": "openapi.json",
            "hash": hashlib.sha256(openapi_bytes).hexdigest(),
            "path_count": len(openapi.get("paths", {})),
        },
    )

    print(
        json.dumps(
            {
                "collected_at": collected_at,
                "services": len(services),
                "api_status": api_status,
                "web_status": web_status,
                "alembic_current": current_revision,
                "openapi_sha256": hashlib.sha256(openapi_bytes).hexdigest(),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
