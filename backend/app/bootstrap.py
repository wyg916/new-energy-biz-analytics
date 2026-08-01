import json

from sqlalchemy import select

from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.models.auth import User
from app.models.integration import DataSetDefinition, DataSourceConnection
from app.scenarios.charging_ops.manifest import MAPPING_FIELDS
from app.scenarios.registry import install_charging_ops
from app.platform.identity import IdentityContextFactory
from app.skills.definitions import install_initial_skills
from app.query_engines.sqlbot.source_binding import install_initial_source_bindings


DEMO_USERS = (
    ("executive", "AlphaExec!2026", "经营负责人", "executive", None),
    ("regional", "AlphaRegion!2026", "区域运营经理", "regional_manager", "R01"),
    ("analyst", "AlphaAnalyst!2026", "数据分析师/管理员", "analyst_admin", None),
)

def bootstrap_demo_users() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        for username, password, display_name, role, region_code in DEMO_USERS:
            if db.scalar(select(User.id).where(User.username == username)) is None:
                db.add(User(username=username, password_hash=hash_password(password), display_name=display_name, role=role, region_code=region_code))
        sources = (
            ("platform-postgresql", "PostgreSQL", "postgresql", "db", 5432, "renewable_alpha", "alpha", None, None, {"managed_platform": True}),
            ("chatbi-postgresql", "PostgreSQL（chatBI）", "postgresql", "host.docker.internal", 5432, "postgres", "postgres", None, "CHATBI_PG_PASSWORD", {}),
            ("chatbi-mysql", "MySQL", "mysql", "host.docker.internal", 3306, None, "root", None, "CHATBI_MYSQL_PASSWORD", {}),
            ("excel-import", "Excel/CSV", "excel", None, None, None, None, "station_operations.xlsx", None, {}),
            ("api-import", "API", "api", None, None, None, None, None, None, {}),
        )
        for source_id, name, source_type, host, port, database_name, username, locator, credential_key, options in sources:
            existing_source = db.get(DataSourceConnection, source_id)
            if existing_source is None:
                db.add(DataSourceConnection(
                    source_id=source_id, display_name=name, source_type=source_type,
                    host=host, port=port, database_name=database_name, username=username,
                    resource_locator=locator, credential_env_key=credential_key,
                    connection_options_json=json.dumps(options), status="configured",
                ))
            elif credential_key and existing_source.credential_env_key != credential_key:
                existing_source.credential_env_key = credential_key
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
        install_charging_ops(db)
        db.commit()
        admin = db.scalar(select(User).where(User.username == "analyst"))
        if admin is not None:
            identity = IdentityContextFactory.from_user(admin)
            install_initial_skills(db, identity)
            install_initial_source_bindings(db, identity)
