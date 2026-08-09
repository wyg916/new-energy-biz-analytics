from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
EXPECTED_REVISION = "integration_41_merge_0001"


def run_alembic(database_url: str, *arguments: str) -> dict:
    env = dict(os.environ)
    env.update({"APP_ENV": "test", "DATABASE_URL": database_url, "PYTHONPATH": "."})
    process = subprocess.run(
        ["alembic", *arguments],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return {
        "command": ["alembic", *arguments],
        "exit_code": process.returncode,
        "stdout": process.stdout.strip(),
        "stderr": process.stderr.strip(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")

    steps = [
        run_alembic(args.database_url, "upgrade", "data_0001"),
        run_alembic(args.database_url, "upgrade", "head"),
        run_alembic(args.database_url, "downgrade", "data_0001"),
        run_alembic(args.database_url, "upgrade", "head"),
        run_alembic(args.database_url, "current"),
    ]
    engine = create_engine(args.database_url)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        memory_columns = {column["name"] for column in inspector.get_columns("memory_record")}
        version_columns = {
            column["name"] for column in inspector.get_columns("knowledge_document_version")
        }
        chunk_columns = {column["name"] for column in inspector.get_columns("knowledge_chunk")}
        retrieval_columns = {
            column["name"] for column in inspector.get_columns("knowledge_retrieval_event")
        }
        with engine.connect() as connection:
            revisions = list(connection.scalars(text("SELECT version_num FROM alembic_version")))
    finally:
        engine.dispose()

    required_tables = {
        "memory_lifecycle_task",
        "memory_lifecycle_outbox",
        "memory_delete_verification",
        "knowledge_chunk_index",
        "knowledge_governance_event",
    }
    required_columns = {
        "memory_record": {"recall_count", "last_recalled_at", "lifecycle_transition_at"},
        "knowledge_document_version": {
            "parser_name", "parser_version", "chunking_version", "embedding_model",
            "embedding_dimensions", "metadata_json",
        },
        "knowledge_chunk": {"paragraph_start", "paragraph_end", "locator_json"},
        "knowledge_retrieval_event": {
            "rewritten_query_sha256", "keyword_candidate_count", "vector_candidate_count",
            "injection_rejection_count", "refusal_reason", "context_sha256", "rank_config_json",
        },
    }
    columns_ok = (
        required_columns["memory_record"] <= memory_columns
        and required_columns["knowledge_document_version"] <= version_columns
        and required_columns["knowledge_chunk"] <= chunk_columns
        and required_columns["knowledge_retrieval_event"] <= retrieval_columns
    )
    passed = (
        all(step["exit_code"] == 0 for step in steps)
        and revisions == [EXPECTED_REVISION]
        and required_tables <= tables
        and columns_ok
    )
    payload = {
        "status": "PASS" if passed else "FAIL",
        "generated_at": datetime.now(UTC).isoformat(),
        "database_engine": "postgresql",
        "database_url_redacted": True,
        "start_revision": "data_0001",
        "parent_heads": ["memory_41_0001", "rag_0001"],
        "final_revisions": revisions,
        "expected_revision": EXPECTED_REVISION,
        "required_tables": sorted(required_tables),
        "required_columns": {key: sorted(value) for key, value in required_columns.items()},
        "steps": steps,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "final_revisions": revisions}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
