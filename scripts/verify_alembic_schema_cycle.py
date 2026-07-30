"""Verify release upgrade/rollback/re-upgrade in an isolated PostgreSQL schema."""

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

SCHEMA = "v2_p0_6_release_verify"
ROOT = Path("/app")

original_url = os.environ["DATABASE_URL"]
base_engine = create_engine(original_url, pool_pre_ping=True)
schema_engine = None
result = {
    "isolation": "dedicated_schema",
    "schema": SCHEMA,
    "head_revision": None,
    "rollback_revision": "base",
    "base_to_head": False,
    "head_to_base": False,
    "base_to_head_again": False,
    "upgrade": False,
    "rollback": False,
    "reupgrade": False,
    "schema_removed": False,
    "existing_volume_deleted": False,
}

try:
    with base_engine.begin() as connection:
        exists = connection.scalar(
            text("SELECT 1 FROM information_schema.schemata WHERE schema_name = :schema"),
            {"schema": SCHEMA},
        )
        if exists:
            raise RuntimeError(f"refusing to reuse existing schema: {SCHEMA}")
        connection.execute(text(f'CREATE SCHEMA "{SCHEMA}"'))

    url = make_url(original_url)
    query = dict(url.query)
    query["options"] = f"-csearch_path={SCHEMA}"
    schema_url = url.set(query=query).render_as_string(hide_password=False)
    os.environ["DATABASE_URL"] = schema_url.replace("%", "%%")

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    revisions = ScriptDirectory.from_config(config)
    head_revision = revisions.get_current_head()
    result["head_revision"] = head_revision

    command.upgrade(config, "head")
    schema_engine = create_engine(schema_url, pool_pre_ping=True)
    with schema_engine.connect() as connection:
        revision = MigrationContext.configure(connection).get_current_revision()
    result["base_to_head"] = revision == head_revision
    result["upgrade"] = result["base_to_head"]

    command.downgrade(config, "base")
    with schema_engine.connect() as connection:
        revision = MigrationContext.configure(connection).get_current_revision()
    result["head_to_base"] = revision is None
    result["rollback"] = result["head_to_base"]

    command.upgrade(config, "head")
    with schema_engine.connect() as connection:
        revision = MigrationContext.configure(connection).get_current_revision()
    result["base_to_head_again"] = revision == head_revision
    result["reupgrade"] = result["base_to_head_again"]
finally:
    os.environ["DATABASE_URL"] = original_url
    if schema_engine is not None:
        schema_engine.dispose()
    with base_engine.begin() as connection:
        connection.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE'))
        result["schema_removed"] = not bool(
            connection.scalar(
                text("SELECT 1 FROM information_schema.schemata WHERE schema_name = :schema"),
                {"schema": SCHEMA},
            )
        )
    base_engine.dispose()

result["passed"] = all(
    result[key] for key in (
        "base_to_head", "head_to_base", "base_to_head_again", "schema_removed"
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
