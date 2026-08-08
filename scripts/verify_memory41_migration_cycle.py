from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def run_alembic(database_url: str, *arguments: str) -> dict:
    env = dict(os.environ)
    env.update({"APP_ENV": "test", "DATABASE_URL": database_url, "PYTHONPATH": "."})
    process = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return {
        "command": ["python", "-m", "alembic", *arguments],
        "exit_code": process.returncode,
        "stdout": process.stdout.strip(),
        "stderr": process.stderr.strip(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    steps = [
        run_alembic(args.database_url, "upgrade", "head"),
        run_alembic(args.database_url, "downgrade", "data_0001"),
        run_alembic(args.database_url, "upgrade", "head"),
        run_alembic(args.database_url, "current"),
    ]
    engine = create_engine(args.database_url)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        columns = {column["name"] for column in inspector.get_columns("memory_record")}
        with engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    finally:
        engine.dispose()
    required_tables = {
        "memory_lifecycle_task",
        "memory_lifecycle_outbox",
        "memory_delete_verification",
    }
    required_columns = {"recall_count", "last_recalled_at", "lifecycle_transition_at"}
    passed = (
        all(step["exit_code"] == 0 for step in steps)
        and revision == "memory_41_0001"
        and required_tables <= tables
        and required_columns <= columns
    )
    payload = {
        "status": "PASS" if passed else "FAIL",
        "generated_at": datetime.now(UTC).isoformat(),
        "database_engine": "postgresql" if args.database_url.startswith("postgresql") else "sqlite",
        "database_url_redacted": True,
        "start_revision": "data_0001",
        "final_revision": revision,
        "required_tables": sorted(required_tables),
        "required_columns": sorted(required_columns),
        "steps": steps,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "final_revision": revision}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
