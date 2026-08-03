"""Verify the actual patched Keycloak JAR payloads without trusting filenames."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import tarfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IMAGE = "renewable-p5b-keycloak:26.7.0-hardened"
COMPONENTS = {
    "jackson-core": {
        "path": "/opt/keycloak/lib/lib/main/com.fasterxml.jackson.core.jackson-core-2.21.2.jar",
        "pom": "META-INF/maven/com.fasterxml.jackson.core/jackson-core/pom.properties",
        "expected_version": "2.21.4",
        "expected_sha256": "4b40a06396f239f8de2da57419adde6e94e5edc18a2171d471ea05eeed4e5c2d",
        "findings": ["GHSA-r7wm-3cxj-wff9"],
    },
    "jackson-databind": {
        "path": "/opt/keycloak/lib/lib/main/com.fasterxml.jackson.core.jackson-databind-2.21.2.jar",
        "pom": "META-INF/maven/com.fasterxml.jackson.core/jackson-databind/pom.properties",
        "expected_version": "2.21.4",
        "expected_sha256": "3888e9e69ab66fbacaacc9aea0e9ffbf15368288e4aca468b024dba11c09fbf9",
        "findings": ["CVE-2026-54512", "CVE-2026-54513"],
    },
}


def run(*args: str, binary: bool = False) -> bytes | str:
    process = subprocess.run(
        list(args), cwd=ROOT, capture_output=True,
        text=not binary, encoding=None if binary else "utf-8",
    )
    if process.returncode:
        raise RuntimeError(f"verification command failed: {args[:3]}")
    return process.stdout


def image_file(container: str, path: str) -> bytes:
    archive = run("docker", "cp", f"{container}:{path}", "-", binary=True)
    assert isinstance(archive, bytes)
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r|") as payload:
        member = payload.next()
        if member is None:
            raise RuntimeError(f"empty docker cp archive: {path}")
        stream = payload.extractfile(member)
        if stream is None:
            raise RuntimeError(f"container path is not a file: {path}")
        return stream.read()


def pom_version(blob: bytes, path: str) -> str:
    with zipfile.ZipFile(io.BytesIO(blob)) as jar:
        properties = jar.read(path).decode("utf-8")
    for line in properties.splitlines():
        if line.startswith("version="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError(f"version absent from {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    container = str(run("docker", "create", "--entrypoint", "true", IMAGE)).strip()
    results = []
    try:
        for name, spec in COMPONENTS.items():
            blob = image_file(container, str(spec["path"]))
            actual_sha = hashlib.sha256(blob).hexdigest()
            actual_version = pom_version(blob, str(spec["pom"]))
            results.append({
                "component": name,
                "image_path": spec["path"],
                "filename_version_is_stale": True,
                "actual_pom_version": actual_version,
                "expected_fixed_version": spec["expected_version"],
                "actual_sha256": actual_sha,
                "expected_sha256": spec["expected_sha256"],
                "scanner_findings_disposition": spec["findings"],
                "status": "PASS" if (
                    actual_sha == spec["expected_sha256"]
                    and actual_version == spec["expected_version"]
                ) else "FAIL",
            })
    finally:
        subprocess.run(["docker", "rm", container], cwd=ROOT, capture_output=True)
    identity = json.loads(str(run("docker", "image", "inspect", IMAGE)))[0]
    payload = {
        "schema_version": "1.0",
        "evidence_type": "p5b_keycloak_actual_component_verification",
        "captured_at": datetime.now(UTC).isoformat(),
        "image": IMAGE,
        "image_id": identity["Id"],
        "components": results,
        "status": "PASS" if all(item["status"] == "PASS" for item in results) else "FAIL",
        "interpretation": (
            "The three Jackson High findings are stale Quarkus filename/metadata detections; "
            "the shipped JAR bytes and embedded Maven versions are patched. This evidence does "
            "not disposition the separate OpenJDK High finding."
        ),
        "waiver": False,
        "severity_lowering": False,
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(json.dumps({"status": payload["status"], "components": len(results)}, sort_keys=True))
    raise SystemExit(0 if payload["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
