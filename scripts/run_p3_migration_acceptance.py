"""Run base-to-head, rollback, and re-upgrade in a dedicated test database.

This script is intended to run inside the API container. It refuses to reuse
an existing database and removes only the database that it created itself.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


SAFE_DATABASE_NAME = re.compile(r"^[a-z][a-z0-9_]{2,62}$")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        default="p3_governance_migration_verify",
        help="dedicated disposable database name",
    )
    parser.add_argument(
        "--rollback-revision",
        default="base",
        help="revision to downgrade to before the final upgrade",
    )
    parser.add_argument(
        "--rollback-via-revision",
        default=None,
        help=(
            "optional common ancestor used when the target is on one branch of a "
            "multi-head graph; downgrade to it, then upgrade to --rollback-revision"
        ),
    )
    args = parser.parse_args()
    if not SAFE_DATABASE_NAME.fullmatch(args.database):
        parser.error("--database must be a safe lowercase PostgreSQL identifier")

    original_url = os.environ["DATABASE_URL"]
    root = Path("/app") if Path("/app/alembic.ini").is_file() else Path(__file__).resolve().parents[1]
    admin_engine = create_engine(
        original_url,
        pool_pre_ping=True,
        isolation_level="AUTOCOMMIT",
    )
    verification_engine = None
    created = False
    report = {
        "evidence_type": "p3_migration_acceptance",
        "isolation": "dedicated_database",
        "database": args.database,
        "head_revision": None,
        "base_to_head": False,
        "rollback_revision": args.rollback_revision,
        "rollback_via_revision": args.rollback_via_revision,
        "observed_via_heads": None,
        "head_to_rollback": False,
        "rollback_to_head": False,
        "database_removed": False,
        "existing_volume_deleted": False,
    }

    try:
        with admin_engine.connect() as connection:
            exists = connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :database"),
                {"database": args.database},
            )
            if exists:
                raise RuntimeError(
                    f"refusing to reuse existing database: {args.database}"
                )
            connection.execute(text(f'CREATE DATABASE "{args.database}"'))
            created = True

        verification_url = make_url(original_url).set(database=args.database)
        os.environ["DATABASE_URL"] = verification_url.render_as_string(
            hide_password=False
        )
        config = Config(str(root / "alembic.ini"))
        config.set_main_option("script_location", str(root / "alembic"))
        scripts = ScriptDirectory.from_config(config)
        report["head_revision"] = scripts.get_current_head()

        command.upgrade(config, "head")
        verification_engine = create_engine(verification_url, pool_pre_ping=True)
        with verification_engine.connect() as connection:
            heads = tuple(MigrationContext.configure(connection).get_current_heads())
        report["observed_head_revisions"] = list(heads)
        report["base_to_head"] = heads == (report["head_revision"],)

        if args.rollback_revision != "base" and scripts.get_revision(args.rollback_revision) is None:
            raise RuntimeError(f"unknown rollback revision: {args.rollback_revision}")
        if args.rollback_via_revision is not None:
            if args.rollback_revision == "base":
                raise RuntimeError("--rollback-via-revision cannot be used with a base target")
            if scripts.get_revision(args.rollback_via_revision) is None:
                raise RuntimeError(
                    f"unknown rollback via revision: {args.rollback_via_revision}"
                )
            command.downgrade(config, args.rollback_via_revision)
            with verification_engine.connect() as connection:
                via_heads = tuple(
                    MigrationContext.configure(connection).get_current_heads()
                )
            report["observed_via_heads"] = list(via_heads)
            if via_heads != (args.rollback_via_revision,):
                raise RuntimeError(
                    "downgrade did not converge on the requested common ancestor: "
                    f"expected {(args.rollback_via_revision,)}, observed {via_heads}"
                )
            command.upgrade(config, args.rollback_revision)
        else:
            command.downgrade(config, args.rollback_revision)
        with verification_engine.connect() as connection:
            rollback_heads = tuple(
                MigrationContext.configure(connection).get_current_heads()
            )
        expected_rollback = () if args.rollback_revision == "base" else (args.rollback_revision,)
        report["observed_rollback_revisions"] = list(rollback_heads)
        report["head_to_rollback"] = rollback_heads == expected_rollback

        command.upgrade(config, "head")
        with verification_engine.connect() as connection:
            heads = tuple(MigrationContext.configure(connection).get_current_heads())
        report["observed_reupgrade_revisions"] = list(heads)
        report["rollback_to_head"] = heads == (report["head_revision"],)
    finally:
        os.environ["DATABASE_URL"] = original_url
        if verification_engine is not None:
            verification_engine.dispose()
        if created:
            with admin_engine.connect() as connection:
                connection.execute(text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :database AND pid <> pg_backend_pid()"
                ), {"database": args.database})
                connection.execute(text(f'DROP DATABASE "{args.database}"'))
                report["database_removed"] = not bool(connection.scalar(
                    text("SELECT 1 FROM pg_database WHERE datname = :database"),
                    {"database": args.database},
                ))
        admin_engine.dispose()

    report["passed"] = all(report[key] for key in (
        "base_to_head", "head_to_rollback", "rollback_to_head", "database_removed"
    ))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
