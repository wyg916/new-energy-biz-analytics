"""Prepare the isolated 0014 PostgreSQL acceptance baseline without create_all."""

from __future__ import annotations

import json

from sqlalchemy import select, text

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.data.seed import generate_simulated_data
from app.models.auth import User
from app.models.integration import DataSetDefinition, DataSourceConnection
from app.platform.identity import IdentityContextFactory
from app.scenarios.charging_ops.manifest import MAPPING_FIELDS
from app.scenarios.charging_ops.package_adapter import install_platform_foundation
from app.scenarios.sales_ops.package_adapter import install_sales_ops_foundation
from app.scenarios.sales_ops.seed import generate_sales_orders


def main() -> None:
    with SessionLocal() as db:
        revision = db.scalar(text("SELECT version_num FROM alembic_version"))
        if revision != "0014":
            raise RuntimeError(f"acceptance baseline must be prepared at 0014, got {revision}")
        analyst = db.scalar(select(User).where(User.username == "analyst"))
        if analyst is None:
            analyst = User(
                username="analyst",
                password_hash=hash_password("AlphaAnalyst!2026"),
                display_name="数据分析师/管理员",
                role="analyst_admin",
                region_code=None,
                is_active=True,
            )
            db.add(analyst)
            db.commit()
        if db.get(DataSourceConnection, "platform-postgresql") is None:
            db.add(DataSourceConnection(
                source_id="platform-postgresql",
                display_name="PostgreSQL",
                source_type="postgresql",
                host="db",
                port=5432,
                database_name="renewable_alpha",
                username="alpha",
                resource_locator=None,
                credential_env_key=None,
                connection_options_json=json.dumps({"managed_platform": True}),
                status="configured",
            ))
            db.flush()
        if db.get(DataSetDefinition, "station-operations") is None:
            db.add(DataSetDefinition(
                dataset_id="station-operations",
                source_id="platform-postgresql",
                display_name="场站经营指标视图",
                source_object="dashboard/stations",
                target_table="ingested_station_preview",
                standard_schema="charging_ops",
                mapping_json=json.dumps(MAPPING_FIELDS, ensure_ascii=False),
                data_classification="simulated",
                status="validated",
            ))
        db.commit()
        identity = IdentityContextFactory.from_user(analyst)
        charging_counts = generate_simulated_data(db, session_count=300_000)
        charging_platform = install_platform_foundation(db, identity)
        sales_summary = generate_sales_orders(db)
        sales_platform = install_sales_ops_foundation(db, identity)
        print(json.dumps({
            "data_classification": "simulated",
            "alembic_revision": revision,
            "charging": charging_counts,
            "charging_platform": charging_platform,
            "sales": sales_summary.as_dict(),
            "sales_platform": sales_platform,
        }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
