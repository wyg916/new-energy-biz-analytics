"""Verify release upgrade/rollback/re-upgrade in an isolated PostgreSQL database."""

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

INNER_SCRIPT = r'''
import json
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

DATABASE = "v2_p2a_release_verify"
ROOT = Path("/app")

original_url = os.environ["DATABASE_URL"]
admin_engine = create_engine(
    original_url,
    pool_pre_ping=True,
    isolation_level="AUTOCOMMIT",
)
verification_engine = None
result = {
    "isolation": "dedicated_database",
    "database": DATABASE,
    "head_revision": None,
    "rollback_revision": "base",
    "base_to_head": False,
    "head_to_base": False,
    "base_to_head_again": False,
    "upgrade": False,
    "rollback": False,
    "reupgrade": False,
    "database_removed": False,
    "existing_volume_deleted": False,
}

try:
    with admin_engine.connect() as connection:
        exists = connection.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :database"),
            {"database": DATABASE},
        )
        if exists:
            raise RuntimeError(f"refusing to reuse existing database: {DATABASE}")
        connection.execute(text(f'CREATE DATABASE "{DATABASE}"'))

    url = make_url(original_url)
    verification_url = url.set(database=DATABASE).render_as_string(
        hide_password=False
    )
    os.environ["DATABASE_URL"] = verification_url.replace("%", "%%")

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    revisions = ScriptDirectory.from_config(config)
    head_revision = revisions.get_current_head()
    result["head_revision"] = head_revision

    command.upgrade(config, "head")
    verification_engine = create_engine(verification_url, pool_pre_ping=True)
    with verification_engine.connect() as connection:
        revision = MigrationContext.configure(connection).get_current_revision()
    result["base_to_head"] = revision == head_revision
    result["upgrade"] = result["base_to_head"]

    command.downgrade(config, "base")
    with verification_engine.connect() as connection:
        revision = MigrationContext.configure(connection).get_current_revision()
    result["head_to_base"] = revision is None
    result["rollback"] = result["head_to_base"]

    command.upgrade(config, "head")
    with verification_engine.connect() as connection:
        revision = MigrationContext.configure(connection).get_current_revision()
    result["base_to_head_again"] = revision == head_revision
    result["reupgrade"] = result["base_to_head_again"]
finally:
    os.environ["DATABASE_URL"] = original_url
    if verification_engine is not None:
        verification_engine.dispose()
    with admin_engine.connect() as connection:
        connection.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :database AND pid <> pg_backend_pid()"
            ),
            {"database": DATABASE},
        )
        connection.execute(text(f'DROP DATABASE IF EXISTS "{DATABASE}"'))
        result["database_removed"] = not bool(
            connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :database"),
                {"database": DATABASE},
            )
        )
    admin_engine.dispose()

result["passed"] = all(
    result[key] for key in (
        "base_to_head", "head_to_base", "base_to_head_again", "database_removed"
    )
)
print(json.dumps(result, ensure_ascii=False))
raise SystemExit(0 if result["passed"] else 1)
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    process = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-"],
        cwd=ROOT,
        input=INNER_SCRIPT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    if process.stdout:
        print(process.stdout, end="")
    if process.stderr:
        print(process.stderr, end="", file=sys.stderr)
    if args.output is not None and process.stdout:
        payload = json.loads(process.stdout.strip().splitlines()[-1])
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return process.returncode


if __name__ == "__main__":
    raise SystemExit(main())
