"""Verify the integrated migration, RAG index and Memory scheduler runtime."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from sqlalchemy import func, select, text
from redis import Redis

from app.core.config import get_settings
from app.ai.model_gateway.runtime import runtime_model_status
from app.core.database import SessionLocal
from app.memory.models import MemoryLifecycleTask
from app.models.knowledge import KnowledgeDocumentVersion
from scripts.rebuild_rag_indexes import inspect_index_state


EXPECTED_REVISION = "integration_41_full_0001"


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
        published_document_count = int(db.scalar(
            select(func.count()).select_from(KnowledgeDocumentVersion).where(
                KnowledgeDocumentVersion.status == "PUBLISHED"
            )
        ) or 0)
        p6_table_count = int(db.scalar(text("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name LIKE 'p6_%'
        """)) or 0)
        semantic_view_count = int(db.scalar(text("""
            SELECT COUNT(*) FROM information_schema.views
            WHERE table_schema IN ('semantic_sqlbot_charging', 'semantic_sqlbot_sales')
        """)) or 0)
        active_binding_count = int(db.scalar(text("""
            SELECT COUNT(*) FROM sqlbot_source_binding_release WHERE status = 'ACTIVE'
        """)) or 0)
    rag = inspect_index_state()
    model_gateway = runtime_model_status()
    redis_ready = bool(Redis.from_url(settings.redis_url).ping())
    readonly_file = Path("/run/p4-runtime/sqlbot41b_readonly_credentials.json")
    checks = {
        "migration_head": revision == expected_revision,
        "settings_revision": settings.expected_database_revision == expected_revision,
        "rag_index_reconciled": bool(rag["index_ready"]),
        "knowledge_published": published_document_count > 0,
        "knowledge_chunks_published": rag["chunk_count"] > 0,
        "memory_scheduler_enabled": settings.memory_lifecycle_scheduler_enabled,
        "memory_scheduler_created_tasks": lifecycle_task_count > 0,
        "memory_scheduler_no_failed_tasks": lifecycle_failed_count == 0,
        "redis_ready": redis_ready,
        "p6_tables_ready": p6_table_count >= 10,
        "sqlbot_semantic_views_ready": semantic_view_count == 16,
        "sqlbot_source_bindings_ready": active_binding_count == 2,
        "sqlbot_readonly_credentials_ready": readonly_file.is_file(),
        "deterministic_query_engine": (
            settings.effective_query_engine_mode == "DETERMINISTIC_ONLY"
        ),
        "sqlbot_engine_disabled": not settings.sqlbot_engine_enabled,
        "sqlbot_runtime_unverified": not settings.sqlbot_runtime_verified,
        "sqlbot_registered_not_eligible": (
            settings.sqlbot_provider_eligibility == "REGISTERED_NOT_ELIGIBLE"
        ),
        "sqlbot_release_included": settings.sqlbot_included_in_v4_release,
        "model_gateway_ready": model_gateway["status"] == "READY",
        "model_gateway_three_providers_registered": sum(
            item["configured"] and item["enabled"]
            for item in model_gateway["providers"]
        ) == 3,
    }
    return {
        "status": "PASS" if all(checks.values()) else "WAITING",
        "revision": revision,
        "expected_revision": expected_revision,
        "rag": rag,
        "lifecycle_task_count": lifecycle_task_count,
        "lifecycle_failed_count": lifecycle_failed_count,
        "published_document_count": published_document_count,
        "p6_table_count": p6_table_count,
        "semantic_view_count": semantic_view_count,
        "active_binding_count": active_binding_count,
        "query_engine_mode": settings.effective_query_engine_mode,
        "sqlbot_provider_eligibility": settings.sqlbot_provider_eligibility,
        "model_gateway": model_gateway,
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
