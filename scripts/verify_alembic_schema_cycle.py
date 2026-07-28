"""Verify Alembic upgrade/downgrade/re-upgrade in an isolated PostgreSQL schema."""

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
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

SCHEMA = "v2_p0_0_alembic_verify"
ROOT = Path("/app")

original_url = os.environ["DATABASE_URL"]
base_engine = create_engine(original_url, pool_pre_ping=True)
schema_engine = None
result = {
    "isolation": "dedicated_schema",
    "schema": SCHEMA,
    "upgrade": False,
    "downgrade": False,
    "reupgrade": False,
    "schema_removed": False,
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

    command.upgrade(config, "head")
    schema_engine = create_engine(schema_url, pool_pre_ping=True)
    with schema_engine.connect() as connection:
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    result["upgrade"] = revision == "0003"

    command.downgrade(config, "base")
    remaining = inspect(schema_engine).get_table_names(schema=SCHEMA)
    result["downgrade"] = remaining in ([], ["alembic_version"])

    command.upgrade(config, "head")
    with schema_engine.connect() as connection:
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    result["reupgrade"] = revision == "0003"
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
    result[key] for key in ("upgrade", "downgrade", "reupgrade", "schema_removed")
)
print(json.dumps(result, ensure_ascii=False))
raise SystemExit(0 if result["passed"] else 1)
'''


def main() -> int:
    process = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-"],
        cwd=ROOT,
        input=INNER_SCRIPT,
        text=True,
        encoding="utf-8",
    )
    return process.returncode


if __name__ == "__main__":
    raise SystemExit(main())
