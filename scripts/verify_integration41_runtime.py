"""Verify the integrated migration, RAG index and Memory scheduler runtime."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from sqlalchemy import func, select, text

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.memory.models import MemoryLifecycleTask
from scripts.rebuild_rag_indexes import inspect_index_state


EXPECTED_REVISION = "integration_41_merge_0001"


def snapshot(expected_revision: str = EXPECTED_REVISION) -> dict:
    settings = get_settings()
    with SessionLocal() as db:
        revision = db.scalar(text("SELECT version_num FROM alembic_version"))
        lifecycle_task_count = int(
            db.scalar(select(func.count()).select_from(MemoryLifecycleTask)) or 0
        )
        lifecycle_failed_count = int(db.scalar(
            select(func.count()).select_from(MemoryLifecycleTask).where(
                MemoryLifecycleTask.status == "FAILED"
            )
        ) or 0)
    rag = inspect_index_state()
    checks = {
        "migration_head": revision == expected_revision,
        "settings_revision": settings.expected_database_revision == expected_revision,
        "rag_index_reconciled": bool(rag["index_ready"]),
        "memory_scheduler_enabled": settings.memory_lifecycle_scheduler_enabled,
        "memory_scheduler_created_tasks": lifecycle_task_count > 0,
        "memory_scheduler_no_failed_tasks": lifecycle_failed_count == 0,
        "sqlbot_shadow": settings.effective_query_engine_mode == "SHADOW",
        "sqlbot_engine_disabled": not settings.sqlbot_engine_enabled,
        "sqlbot_release_disabled": not settings.sqlbot_included_in_v4_release,
    }
    return {
        "status": "PASS" if all(checks.values()) else "WAITING",
        "revision": revision,
        "expected_revision": expected_revision,
        "rag": rag,
        "lifecycle_task_count": lifecycle_task_count,
        "lifecycle_failed_count": lifecycle_failed_count,
        "query_engine_mode": settings.effective_query_engine_mode,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout-seconds", type=int, default=45)
    parser.add_argument("--expected-revision", default=EXPECTED_REVISION)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    deadline = time.monotonic() + max(args.timeout_seconds, 0)
    result = snapshot(args.expected_revision)
    while result["status"] != "PASS" and time.monotonic() < deadline:
        time.sleep(1)
        result = snapshot(args.expected_revision)
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
