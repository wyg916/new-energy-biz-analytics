#!/usr/bin/env python3
"""Install the knowledge baseline into an extracted project repository.

- Verifies package files.
- Idempotently adds source paths to backend/app/knowledge/approved_sources.py.
- Does NOT store or request secrets.
- Does NOT publish knowledge automatically.
"""
from __future__ import annotations
from pathlib import Path
import argparse, ast, hashlib, json, sys

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = PACKAGE_ROOT / "integration" / "knowledge_manifest.json"
PATHS_FILE = PACKAGE_ROOT / "integration" / "approved_sources_paths.txt"

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def verify_package():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    errors = []
    for item in data["files"]:
        p = PACKAGE_ROOT / item["path"]
        if not p.is_file():
            errors.append(f"missing: {item['path']}")
            continue
        got = sha256(p)
        if got != item["sha256"]:
            errors.append(f"sha256 mismatch: {item['path']}")
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"[PASS] package integrity: {len(data['files'])} files")

def patch_allowlist(repo_root: Path):
    target = repo_root / "backend" / "app" / "knowledge" / "approved_sources.py"
    if not target.is_file():
        raise SystemExit(f"repository file not found: {target}")
    text = target.read_text(encoding="utf-8")
    paths = [x.strip() for x in PATHS_FILE.read_text(encoding="utf-8").splitlines() if x.strip()]
    missing = [p for p in paths if f'"{p}"' not in text]
    if not missing:
        print("[PASS] approved source allowlist already contains baseline paths")
        return

    marker = "\n})"
    idx = text.rfind(marker)
    if idx < 0:
        raise SystemExit("cannot locate APPROVED_SOURCE_PATHS frozenset closing marker")

    addition = "".join(f'    "{p}",\n' for p in missing)
    new_text = text[:idx] + "\n" + addition + text[idx:]
    ast.parse(new_text)

    backup = target.with_suffix(".py.knowledge_baseline_v1.bak")
    if not backup.exists():
        backup.write_text(text, encoding="utf-8")
    target.write_text(new_text, encoding="utf-8")
    print(f"[PASS] added {len(missing)} approved knowledge source paths")
    print(f"[INFO] backup: {backup}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".", help="project repository root")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()

    verify_package()
    if args.verify_only:
        return
    patch_allowlist(Path(args.repo_root).resolve())
    print("[NEXT] start the application and publish using scripts/publish_knowledge_baseline_v1.py")

if __name__ == "__main__":
    main()
