"""Verify SQLBot 4.1C2 view upgrade, rollback, and re-upgrade."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


DATABASE = "sqlbot41c2_migration_verify"
EXPECTED_HEAD = "sqlbot_41c2"
NEW_RELATIONS = {
    "semantic_sqlbot_charging.fact_device_status_event",
    "semantic_sqlbot_charging.fact_energy_cost",
    "semantic_sqlbot_charging.fact_operation_expense",
    "semantic_sqlbot_sales.sales_business_date",
    "semantic_sqlbot_sales.sales_customer",
    "semantic_sqlbot_sales.sales_product_category",
    "semantic_sqlbot_sales.salesperson",
}


def _config(root: Path) -> Config:
    config = Config(str(root / "backend" / "alembic.ini"))
    config.set_main_option("script_location", str(root / "backend" / "alembic"))
    return config


def _relations(engine) -> set[str]:
    with engine.connect() as connection:
        rows = connection.execute(text("""
            SELECT table_schema || '.' || table_name
            FROM information_schema.views
            WHERE table_schema IN (
                'semantic_sqlbot_charging', 'semantic_sqlbot_sales'
            )
        """))
        return {str(row[0]) for row in rows}


def _columns(engine, schema: str, relation: str) -> set[str]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = :schema AND table_name = :relation
            """),
            {"schema": schema, "relation": relation},
        )
        return {str(row[0]) for row in rows}


def _view_definition(engine, schema: str, relation: str) -> str:
    with engine.connect() as connection:
        return str(connection.scalar(
            text("SELECT pg_get_viewdef((:qualified)::regclass, true)"),
            {"qualified": f"{schema}.{relation}"},
        ) or "")


def _seed_sales_semantic_fixture(engine) -> None:
    definition = {
        "fields": [{
            "table": "order_item_fact",
            "code": "quantity",
            "name": "销售数量",
            "data_type": "integer",
            "physical_field": "quantity",
            "nullable": False,
        }],
        "dimensions": [{
            "code": "category",
            "name": "产品类别",
            "aliases": ["品类"],
            "field_ref": "category_dimension.category_id",
            "data_type": "string",
            "hierarchy": ["category"],
        }],
    }
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO semantic_model (
                semantic_model_id, tenant_id, workspace_id, scenario_id,
                code, name, owner_subject_id, status, created_at
            ) VALUES (
                'SM-SQLBOT41C2-FIXTURE', 'tenant-fixture',
                'workspace-fixture', 'sales_ops', 'sales_fixture',
                'SQLBot migration fixture', 'fixture:migration-verifier',
                'ENABLED', CURRENT_TIMESTAMP
            )
        """))
        connection.execute(text("""
            INSERT INTO semantic_model_version (
                semantic_model_version_id, semantic_model_id, version,
                scenario_version, contract_version, dataset_compatibility_json,
                model_json, checksum, status, created_by, reviewed_by,
                created_at, published_at
            ) VALUES (
                'SMV-SQLBOT41C2-FIXTURE-100', 'SM-SQLBOT41C2-FIXTURE',
                '1.0.0', '1.0.0', '0.1', '{}', :model_json,
                :checksum, 'ACTIVE', 'fixture:migration-verifier',
                'fixture:migration-verifier', CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            )
        """), {
            "model_json": json.dumps(
                definition,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "checksum": "0" * 64,
        })
        connection.execute(text("""
            INSERT INTO semantic_table (
                semantic_table_id, semantic_model_version_id, code, name,
                physical_binding, grain_json, lineage_json
            ) VALUES (
                'ST-SQLBOT41C2-FIXTURE-ITEM',
                'SMV-SQLBOT41C2-FIXTURE-100', 'order_item_fact',
                '模拟销售订单明细', 'sales_order_item',
                '["order_item_id"]', '{}'
            )
        """))
        connection.execute(text("""
            INSERT INTO semantic_field (
                semantic_field_id, semantic_table_id, code, name, data_type,
                physical_field, nullable, classification,
                permission_policy_json, lineage_json
            ) VALUES (
                'SF-SQLBOT41C2-FIXTURE-QUANTITY',
                'ST-SQLBOT41C2-FIXTURE-ITEM', 'quantity', '销售数量',
                'integer', 'quantity', 0, 'internal', '{}', '{}'
            )
        """))
        connection.execute(text("""
            INSERT INTO dimension (
                dimension_id, semantic_model_version_id, code, name,
                aliases_json, field_ref, data_type, hierarchy_json,
                permission_policy_json, lineage_json
            ) VALUES (
                'DIM-SQLBOT41C2-FIXTURE-CATEGORY',
                'SMV-SQLBOT41C2-FIXTURE-100', 'category', '产品类别',
                '["品类"]', 'category_dimension.category_id', 'string',
                '["category"]', '{}', '{}'
            )
        """))


def _sales_semantic_state(engine) -> dict:
    with engine.connect() as connection:
        row = connection.execute(text("""
            SELECT v.version, v.created_by, f.semantic_field_id,
                   d.aliases_json
            FROM semantic_model_version AS v
            JOIN semantic_model AS m
              ON m.semantic_model_id = v.semantic_model_id
            LEFT JOIN semantic_table AS t
              ON t.semantic_model_version_id = v.semantic_model_version_id
             AND t.code = 'order_item_fact'
            LEFT JOIN semantic_field AS f
              ON f.semantic_table_id = t.semantic_table_id
             AND f.code = 'refund_amount'
            LEFT JOIN dimension AS d
              ON d.semantic_model_version_id = v.semantic_model_version_id
             AND d.code = 'category'
            WHERE m.scenario_id = 'sales_ops'
              AND v.status = 'ACTIVE'
        """)).mappings().one()
    return {
        "version": str(row["version"]),
        "created_by": str(row["created_by"]),
        "item_refund_field": row["semantic_field_id"] is not None,
        "category_aliases": json.loads(str(row["aliases_json"])),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    admin_url = os.environ["DATABASE_URL"]
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    verification_engine = None
    result = {
        "evidence_type": "sqlbot41c2_migration_cycle",
        "database": DATABASE,
        "expected_head": EXPECTED_HEAD,
        "upgrade": False,
        "rollback": False,
        "reupgrade": False,
        "database_removed": False,
        "semantic_upgrade": False,
        "semantic_rollback": False,
        "semantic_reupgrade": False,
        "new_relations": sorted(NEW_RELATIONS),
        "secret_values_exposed": False,
    }
    try:
        with admin_engine.connect() as connection:
            exists = connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :database"),
                {"database": DATABASE},
            )
            if exists:
                raise RuntimeError("refusing to reuse migration verification database")
            connection.execute(text(f'CREATE DATABASE "{DATABASE}"'))
        url = make_url(admin_url).set(database=DATABASE)
        verification_url = url.render_as_string(hide_password=False)
        os.environ["DATABASE_URL"] = verification_url.replace("%", "%%")
        verification_engine = create_engine(verification_url)
        config = _config(root)

        command.upgrade(config, "data_0001")
        _seed_sales_semantic_fixture(verification_engine)
        command.upgrade(config, "head")
        relations = _relations(verification_engine)
        charging_columns = _columns(
            verification_engine,
            "semantic_sqlbot_charging",
            "fact_charging_session",
        )
        sales_columns = _columns(
            verification_engine,
            "semantic_sqlbot_sales",
            "sales_order",
        )
        result["upgrade"] = (
            NEW_RELATIONS.issubset(relations)
            and {"device_id", "user_id", "user_segment"}.issubset(charging_columns)
            and {"customer_id", "salesperson_id"}.issubset(sales_columns)
        )
        active_binding_definition = _view_definition(
            verification_engine, "semantic_sqlbot_sales", "sales_order"
        )
        result["active_dataset_binding"] = all(
            marker in active_binding_definition
            for marker in ("semantic_activation", "dataset_version", "source_version")
        )
        semantic = _sales_semantic_state(verification_engine)
        result["semantic_upgrade"] = (
            semantic["version"] == "1.0.1"
            and semantic["created_by"] == "system:sqlbot-41c2-migration"
            and semantic["item_refund_field"]
            and "类别" in semantic["category_aliases"]
        )

        command.downgrade(config, "data_0001")
        rolled_back = _relations(verification_engine)
        charging_columns = _columns(
            verification_engine,
            "semantic_sqlbot_charging",
            "fact_charging_session",
        )
        sales_columns = _columns(
            verification_engine,
            "semantic_sqlbot_sales",
            "sales_order",
        )
        result["rollback"] = (
            not (NEW_RELATIONS & rolled_back)
            and "user_segment" not in charging_columns
            and "salesperson_id" not in sales_columns
            and "semantic_activation" not in _view_definition(
                verification_engine, "semantic_sqlbot_sales", "sales_order"
            )
        )
        semantic = _sales_semantic_state(verification_engine)
        result["semantic_rollback"] = (
            semantic["version"] == "1.0.0"
            and not semantic["item_refund_field"]
            and "类别" not in semantic["category_aliases"]
        )

        command.upgrade(config, "head")
        result["reupgrade"] = (
            NEW_RELATIONS.issubset(_relations(verification_engine))
            and "semantic_activation" in _view_definition(
                verification_engine, "semantic_sqlbot_sales", "sales_order"
            )
        )
        semantic = _sales_semantic_state(verification_engine)
        result["semantic_reupgrade"] = (
            semantic["version"] == "1.0.1"
            and semantic["item_refund_field"]
            and "类别" in semantic["category_aliases"]
        )
    finally:
        os.environ["DATABASE_URL"] = admin_url
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
            result["database_removed"] = not bool(connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :database"),
                {"database": DATABASE},
            ))
        admin_engine.dispose()
    result["status"] = "PASS" if all(
        result[key]
        for key in (
            "upgrade", "active_dataset_binding", "rollback", "reupgrade",
            "semantic_upgrade", "semantic_rollback", "semantic_reupgrade",
            "database_removed",
        )
    ) else "FAIL"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
