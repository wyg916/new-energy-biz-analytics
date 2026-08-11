"""Complete governed SQLBot semantic views and semantic release for 4.1C2.

Revision ID: sqlbot_41c2
Revises: data_0001
"""

import hashlib
import json

import sqlalchemy as sa
from alembic import op


revision = "sqlbot_41c2"
down_revision = "data_0001"
branch_labels = None
depends_on = None


_SEMANTIC_ACTOR = "system:sqlbot-41c2-migration"
_TARGET_SEMANTIC_VERSION = "1.0.1"
_ITEM_REFUND_FIELD = {
    "table": "order_item_fact",
    "code": "refund_amount",
    "name": "明细退款金额",
    "data_type": "number",
    "physical_field": "refund_amount",
    "nullable": False,
}


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _derived_id(prefix: str, source_id: str) -> str:
    digest = hashlib.sha256(f"sqlbot-41c2:{source_id}".encode()).hexdigest()[:32]
    return f"{prefix}-41C2-{digest}"


def _upgrade_sales_semantic_release() -> None:
    bind = op.get_bind()
    releases = bind.execute(sa.text("""
        SELECT v.*
        FROM semantic_model_version AS v
        JOIN semantic_model AS m ON m.semantic_model_id = v.semantic_model_id
        WHERE m.scenario_id = 'sales_ops' AND v.status = 'ACTIVE'
        ORDER BY v.semantic_model_version_id
        FOR UPDATE OF v
    """)).mappings().all()
    for release in releases:
        old_id = str(release["semantic_model_version_id"])
        if str(release["version"]) == _TARGET_SEMANTIC_VERSION:
            continue
        duplicate = bind.scalar(sa.text("""
            SELECT semantic_model_version_id
            FROM semantic_model_version
            WHERE semantic_model_id = :model_id AND version = :version
        """), {
            "model_id": release["semantic_model_id"],
            "version": _TARGET_SEMANTIC_VERSION,
        })
        if duplicate is not None:
            raise RuntimeError("SQLBOT_41C2_SEMANTIC_VERSION_ALREADY_EXISTS")

        definition = json.loads(str(release["model_json"]))
        fields = list(definition.get("fields") or [])
        if not any(
            item.get("table") == "order_item_fact"
            and item.get("code") == "refund_amount"
            for item in fields
        ):
            fields.append(_ITEM_REFUND_FIELD)
        definition["fields"] = fields
        for dimension in definition.get("dimensions") or []:
            if dimension.get("code") == "category":
                dimension["aliases"] = list(dict.fromkeys([
                    *(dimension.get("aliases") or []), "类别",
                ]))
        model_json = _canonical(definition)
        new_id = _derived_id("SMV", old_id)

        bind.execute(sa.text("""
            UPDATE semantic_model_version
            SET status = 'SUPERSEDED'
            WHERE semantic_model_version_id = :old_id AND status = 'ACTIVE'
        """), {"old_id": old_id})
        bind.execute(sa.text("""
            INSERT INTO semantic_model_version (
                semantic_model_version_id, semantic_model_id, version,
                scenario_version, contract_version, dataset_compatibility_json,
                model_json, checksum, status, created_by, reviewed_by,
                created_at, published_at
            ) VALUES (
                :new_id, :model_id, :version, :scenario_version,
                :contract_version, :compatibility, :model_json, :checksum,
                'ACTIVE', :actor, :actor, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
        """), {
            "new_id": new_id,
            "model_id": release["semantic_model_id"],
            "version": _TARGET_SEMANTIC_VERSION,
            "scenario_version": release["scenario_version"],
            "contract_version": release["contract_version"],
            "compatibility": release["dataset_compatibility_json"],
            "model_json": model_json,
            "checksum": hashlib.sha256(model_json.encode()).hexdigest(),
            "actor": _SEMANTIC_ACTOR,
        })
        params = {"old_id": old_id, "new_id": new_id, "actor": _SEMANTIC_ACTOR}
        bind.execute(sa.text("""
            INSERT INTO semantic_table (
                semantic_table_id, semantic_model_version_id, code, name,
                physical_binding, grain_json, lineage_json
            )
            SELECT 'ST-41C2-' || substr(md5(semantic_table_id || :new_id), 1, 32),
                   :new_id, code, name, physical_binding, grain_json, lineage_json
            FROM semantic_table WHERE semantic_model_version_id = :old_id
        """), params)
        bind.execute(sa.text("""
            INSERT INTO semantic_field (
                semantic_field_id, semantic_table_id, code, name, data_type,
                physical_field, nullable, classification,
                permission_policy_json, lineage_json
            )
            SELECT 'SF-41C2-' || substr(md5(f.semantic_field_id || :new_id), 1, 32),
                   'ST-41C2-' || substr(md5(f.semantic_table_id || :new_id), 1, 32),
                   f.code, f.name, f.data_type, f.physical_field, f.nullable,
                   f.classification, f.permission_policy_json, f.lineage_json
            FROM semantic_field AS f
            JOIN semantic_table AS t ON t.semantic_table_id = f.semantic_table_id
            WHERE t.semantic_model_version_id = :old_id
        """), params)
        item_table_id = bind.scalar(sa.text("""
            SELECT semantic_table_id FROM semantic_table
            WHERE semantic_model_version_id = :new_id AND code = 'order_item_fact'
        """), params)
        if item_table_id is None:
            raise RuntimeError("SQLBOT_41C2_ORDER_ITEM_TABLE_MISSING")
        bind.execute(sa.text("""
            INSERT INTO semantic_field (
                semantic_field_id, semantic_table_id, code, name, data_type,
                physical_field, nullable, classification,
                permission_policy_json, lineage_json
            )
            SELECT CAST(:field_id AS varchar(64)),
                   CAST(:table_id AS varchar(64)),
                   'refund_amount', '明细退款金额', 'number',
                   'refund_amount', 0, 'internal', '{}', '{}'
            WHERE NOT EXISTS (
                SELECT 1 FROM semantic_field
                WHERE semantic_table_id = CAST(:table_id AS varchar(64))
                  AND code = 'refund_amount'
            )
        """), {
            "field_id": _derived_id(
                "SF", f"{new_id}:order_item_fact:refund_amount"
            ),
            "table_id": item_table_id,
        })
        for table, id_column, prefix, columns in (
            (
                "metric", "metric_id", "MET",
                "code, name, aliases_json, expression, aggregation, grain_json, "
                "time_field, supported_dimensions_json, filters_json, unit, format, "
                "owner, version, status, permission_policy_json, lineage_json",
            ),
            (
                "dimension", "dimension_id", "DIM",
                "code, name, aliases_json, field_ref, data_type, hierarchy_json, "
                "permission_policy_json, lineage_json",
            ),
            (
                "relationship", "relationship_id", "REL",
                "code, source_table, source_fields_json, target_table, "
                "target_fields_json, cardinality, join_type, status",
            ),
            (
                "time_dimension", "time_dimension_id", "TD",
                "code, field_ref, timezone, grains_json, fiscal_calendar_json",
            ),
            (
                "semantic_filter", "semantic_filter_id", "FLT",
                "code, expression_json, required, permission_policy_json",
            ),
        ):
            projected = columns
            if table == "dimension":
                projected = columns.replace(
                    "aliases_json",
                    """CASE WHEN code = 'category'
                       THEN '["品类","类别"]' ELSE aliases_json END""",
                )
            bind.execute(sa.text(f"""
                INSERT INTO {table} (
                    {id_column}, semantic_model_version_id, {columns}
                )
                SELECT '{prefix}-41C2-' ||
                           substr(md5({id_column} || :new_id), 1, 32),
                       :new_id, {projected}
                FROM {table} WHERE semantic_model_version_id = :old_id
            """), params)
        bind.execute(sa.text("""
            INSERT INTO data_policy (
                data_policy_id, tenant_id, workspace_id,
                semantic_model_version_id, code, roles_json, row_filter_json,
                column_masks_json, export_allowed, status
            )
            SELECT 'POL-41C2-' || substr(md5(data_policy_id || :new_id), 1, 32),
                   tenant_id, workspace_id, :new_id, code, roles_json,
                   row_filter_json, column_masks_json, export_allowed, status
            FROM data_policy WHERE semantic_model_version_id = :old_id
        """), params)
        bind.execute(sa.text("""
            UPDATE semantic_activation
            SET active_semantic_model_version_id = :new_id,
                lock_version = lock_version + 1,
                activated_by = :actor,
                activated_at = CURRENT_TIMESTAMP
            WHERE active_semantic_model_version_id = :old_id
        """), params)


def _downgrade_sales_semantic_release() -> None:
    bind = op.get_bind()
    releases = bind.execute(sa.text("""
        SELECT v.semantic_model_version_id, v.semantic_model_id
        FROM semantic_model_version AS v
        JOIN semantic_model AS m ON m.semantic_model_id = v.semantic_model_id
        WHERE m.scenario_id = 'sales_ops'
          AND v.version = :version AND v.created_by = :actor
        ORDER BY v.semantic_model_version_id
        FOR UPDATE OF v
    """), {
        "version": _TARGET_SEMANTIC_VERSION,
        "actor": _SEMANTIC_ACTOR,
    }).mappings().all()
    for release in releases:
        new_id = str(release["semantic_model_version_id"])
        old_id = bind.scalar(sa.text("""
            SELECT semantic_model_version_id
            FROM semantic_model_version
            WHERE semantic_model_id = :model_id
              AND semantic_model_version_id <> :new_id
              AND status = 'SUPERSEDED'
            ORDER BY created_at DESC, semantic_model_version_id DESC
            LIMIT 1
            FOR UPDATE
        """), {
            "model_id": release["semantic_model_id"],
            "new_id": new_id,
        })
        if old_id is None:
            raise RuntimeError("SQLBOT_41C2_PREVIOUS_SEMANTIC_VERSION_MISSING")
        params = {
            "new_id": new_id,
            "old_id": old_id,
            "actor": f"{_SEMANTIC_ACTOR}:rollback",
        }
        bind.execute(sa.text("""
            UPDATE semantic_activation
            SET active_semantic_model_version_id = :old_id,
                lock_version = lock_version + 1,
                activated_by = :actor,
                activated_at = CURRENT_TIMESTAMP
            WHERE active_semantic_model_version_id = :new_id
        """), params)
        bind.execute(sa.text("""
            UPDATE semantic_model_version SET status = 'RETIRED'
            WHERE semantic_model_version_id = :new_id
        """), params)
        bind.execute(sa.text("""
            UPDATE semantic_model_version SET status = 'ACTIVE'
            WHERE semantic_model_version_id = :old_id
        """), params)
        for table in (
            "data_policy", "semantic_filter", "time_dimension", "relationship",
            "dimension", "metric",
        ):
            bind.execute(sa.text(f"""
                DELETE FROM {table} WHERE semantic_model_version_id = :new_id
            """), params)
        bind.execute(sa.text("""
            DELETE FROM semantic_field
            WHERE semantic_table_id IN (
                SELECT semantic_table_id FROM semantic_table
                WHERE semantic_model_version_id = :new_id
            )
        """), params)
        bind.execute(sa.text("""
            DELETE FROM semantic_table WHERE semantic_model_version_id = :new_id
        """), params)
        bind.execute(sa.text("""
            DELETE FROM semantic_model_version
            WHERE semantic_model_version_id = :new_id
        """), params)


def _postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _restore_role_grants() -> None:
    grants = (
        (
            "semantic_sqlbot_charging",
            "sqlbot_platform_charging_readonly",
        ),
        ("semantic_sqlbot_charging", "sqlbot_charging_readonly"),
        ("semantic_sqlbot_sales", "sqlbot_platform_sales_readonly"),
        ("semantic_sqlbot_sales", "sqlbot_sales_readonly"),
    )
    for schema, role in grants:
        op.execute(f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                    GRANT SELECT ON ALL TABLES IN SCHEMA {schema} TO {role};
                END IF;
            END
            $$
        """)


def upgrade() -> None:
    if not _postgresql():
        return
    op.execute("""
        CREATE OR REPLACE VIEW semantic_sqlbot_charging.fact_charging_session AS
        SELECT
            s.session_id, s.station_id, s.start_time, s.end_time,
            s.settlement_time, s.charging_duration_seconds, s.energy_kwh,
            s.electricity_fee_net_amount, s.service_fee_net_amount,
            s.session_status, s.batch_id,
            'simulated'::text AS data_classification,
            s.device_id, s.user_id, u.user_segment
        FROM public.fact_charging_session AS s
        LEFT JOIN public.dim_user AS u ON s.user_id = u.user_id
    """)
    op.execute("""
        CREATE OR REPLACE VIEW semantic_sqlbot_charging.dim_station AS
        SELECT
            station_id, station_name, city_id, region_id, operator_code,
            station_type, open_date, connector_count, rated_power_kw, status,
            'simulated'::text AS data_classification,
            operator_code AS operator
        FROM public.dim_station
    """)
    op.execute("""
        CREATE VIEW semantic_sqlbot_charging.fact_energy_cost AS
        SELECT station_id, cost_date, tariff_period, energy_cost, batch_id,
               'simulated'::text AS data_classification
        FROM public.fact_energy_cost
    """)
    op.execute("""
        CREATE VIEW semantic_sqlbot_charging.fact_operation_expense AS
        SELECT station_id, expense_date, expense_type, amount, is_variable,
               batch_id, 'simulated'::text AS data_classification
        FROM public.fact_operation_expense
    """)
    op.execute("""
        CREATE VIEW semantic_sqlbot_charging.fact_device_status_event AS
        SELECT status_event_id, device_id, station_id, status, start_time,
               end_time, batch_id, 'simulated'::text AS data_classification
        FROM public.fact_device_status_event
    """)
    op.execute("""
        CREATE OR REPLACE VIEW semantic_sqlbot_sales.sales_order AS
        SELECT
            order_id, order_date, channel_id, region_id, organization_code,
            gross_amount, discount_amount, refund_amount, net_revenue,
            cost_amount, gross_profit, status, is_new_customer,
            data_classification, seed_run_id, customer_id, salesperson_id
        FROM public.sales_order
        WHERE seed_run_id IN (
            SELECT dv.source_version
            FROM public.semantic_activation AS a
            JOIN public.dataset_version AS dv
              ON dv.dataset_version_id = a.active_dataset_version_id
             AND dv.status = 'ACTIVE'
            WHERE a.scenario_id = 'sales_ops'
        )
    """)
    op.execute("""
        CREATE OR REPLACE VIEW semantic_sqlbot_sales.sales_order_item AS
        SELECT
            order_item_id, order_id, line_number, product_id, quantity,
            unit_price, gross_amount, discount_amount, refund_amount,
            net_revenue, cost_amount, gross_profit, data_classification,
            seed_run_id
        FROM public.sales_order_item
        WHERE seed_run_id IN (
            SELECT dv.source_version
            FROM public.semantic_activation AS a
            JOIN public.dataset_version AS dv
              ON dv.dataset_version_id = a.active_dataset_version_id
             AND dv.status = 'ACTIVE'
            WHERE a.scenario_id = 'sales_ops'
        )
    """)
    op.execute("""
        CREATE OR REPLACE VIEW semantic_sqlbot_sales.sales_region AS
        SELECT region_id, region_name, organization_code, data_classification
        FROM public.sales_region
        WHERE region_id IN (
            SELECT DISTINCT o.region_id
            FROM public.sales_order AS o
            JOIN public.semantic_activation AS a
              ON a.scenario_id = 'sales_ops'
            JOIN public.dataset_version AS dv
              ON dv.dataset_version_id = a.active_dataset_version_id
             AND dv.status = 'ACTIVE'
             AND dv.source_version = o.seed_run_id
        )
    """)
    op.execute("""
        CREATE OR REPLACE VIEW semantic_sqlbot_sales.sales_channel AS
        SELECT channel_id, channel_name, channel_type, data_classification
        FROM public.sales_channel
        WHERE channel_id IN (
            SELECT DISTINCT o.channel_id
            FROM public.sales_order AS o
            JOIN public.semantic_activation AS a
              ON a.scenario_id = 'sales_ops'
            JOIN public.dataset_version AS dv
              ON dv.dataset_version_id = a.active_dataset_version_id
             AND dv.status = 'ACTIVE'
             AND dv.source_version = o.seed_run_id
        )
    """)
    op.execute("""
        CREATE OR REPLACE VIEW semantic_sqlbot_sales.sales_product AS
        SELECT
            product_id, product_name, category_id, list_price, standard_cost,
            data_classification
        FROM public.sales_product
        WHERE product_id IN (
            SELECT DISTINCT i.product_id
            FROM public.sales_order_item AS i
            JOIN public.semantic_activation AS a
              ON a.scenario_id = 'sales_ops'
            JOIN public.dataset_version AS dv
              ON dv.dataset_version_id = a.active_dataset_version_id
             AND dv.status = 'ACTIVE'
             AND dv.source_version = i.seed_run_id
        )
    """)
    op.execute("""
        CREATE VIEW semantic_sqlbot_sales.sales_customer AS
        SELECT customer_id, customer_segment, data_classification
        FROM public.sales_customer
        WHERE customer_id IN (
            SELECT DISTINCT o.customer_id
            FROM public.sales_order AS o
            JOIN public.semantic_activation AS a
              ON a.scenario_id = 'sales_ops'
            JOIN public.dataset_version AS dv
              ON dv.dataset_version_id = a.active_dataset_version_id
             AND dv.status = 'ACTIVE'
             AND dv.source_version = o.seed_run_id
        )
    """)
    op.execute("""
        CREATE VIEW semantic_sqlbot_sales.sales_product_category AS
        SELECT category_id, category_name, data_classification
        FROM public.sales_product_category
        WHERE category_id IN (
            SELECT DISTINCT p.category_id
            FROM public.sales_product AS p
            JOIN public.sales_order_item AS i ON i.product_id = p.product_id
            JOIN public.semantic_activation AS a
              ON a.scenario_id = 'sales_ops'
            JOIN public.dataset_version AS dv
              ON dv.dataset_version_id = a.active_dataset_version_id
             AND dv.status = 'ACTIVE'
             AND dv.source_version = i.seed_run_id
        )
    """)
    op.execute("""
        CREATE VIEW semantic_sqlbot_sales.salesperson AS
        SELECT salesperson_id, salesperson_name, region_id, organization_code,
               data_classification
        FROM public.salesperson
        WHERE salesperson_id IN (
            SELECT DISTINCT o.salesperson_id
            FROM public.sales_order AS o
            JOIN public.semantic_activation AS a
              ON a.scenario_id = 'sales_ops'
            JOIN public.dataset_version AS dv
              ON dv.dataset_version_id = a.active_dataset_version_id
             AND dv.status = 'ACTIVE'
             AND dv.source_version = o.seed_run_id
        )
    """)
    op.execute("""
        CREATE VIEW semantic_sqlbot_sales.sales_business_date AS
        SELECT business_date, year, quarter, month, week
        FROM public.sales_business_date
        WHERE business_date >= (
            SELECT MIN(dv.period_start::date)
            FROM public.semantic_activation AS a
            JOIN public.dataset_version AS dv
              ON dv.dataset_version_id = a.active_dataset_version_id
             AND dv.status = 'ACTIVE'
            WHERE a.scenario_id = 'sales_ops'
        )
          AND business_date < (
            SELECT MAX(dv.period_end_exclusive::date)
            FROM public.semantic_activation AS a
            JOIN public.dataset_version AS dv
              ON dv.dataset_version_id = a.active_dataset_version_id
             AND dv.status = 'ACTIVE'
            WHERE a.scenario_id = 'sales_ops'
        )
    """)
    _upgrade_sales_semantic_release()
    _restore_role_grants()


def downgrade() -> None:
    if not _postgresql():
        return
    _downgrade_sales_semantic_release()
    for relation in (
        "sales_business_date",
        "salesperson",
        "sales_product_category",
        "sales_customer",
    ):
        op.execute(f"DROP VIEW semantic_sqlbot_sales.{relation}")
    op.execute("DROP VIEW semantic_sqlbot_sales.sales_order")
    op.execute("""
        CREATE VIEW semantic_sqlbot_sales.sales_order AS
        SELECT
            order_id, order_date, channel_id, region_id, organization_code,
            gross_amount, discount_amount, refund_amount, net_revenue,
            cost_amount, gross_profit, status, is_new_customer,
            data_classification, seed_run_id
        FROM public.sales_order
    """)
    op.execute("""
        CREATE OR REPLACE VIEW semantic_sqlbot_sales.sales_order_item AS
        SELECT
            order_item_id, order_id, line_number, product_id, quantity,
            unit_price, gross_amount, discount_amount, refund_amount,
            net_revenue, cost_amount, gross_profit, data_classification,
            seed_run_id
        FROM public.sales_order_item
    """)
    op.execute("""
        CREATE OR REPLACE VIEW semantic_sqlbot_sales.sales_region AS
        SELECT region_id, region_name, organization_code, data_classification
        FROM public.sales_region
    """)
    op.execute("""
        CREATE OR REPLACE VIEW semantic_sqlbot_sales.sales_channel AS
        SELECT channel_id, channel_name, channel_type, data_classification
        FROM public.sales_channel
    """)
    op.execute("""
        CREATE OR REPLACE VIEW semantic_sqlbot_sales.sales_product AS
        SELECT
            product_id, product_name, category_id, list_price, standard_cost,
            data_classification
        FROM public.sales_product
    """)
    for relation in (
        "fact_device_status_event",
        "fact_operation_expense",
        "fact_energy_cost",
    ):
        op.execute(f"DROP VIEW semantic_sqlbot_charging.{relation}")
    op.execute("DROP VIEW semantic_sqlbot_charging.fact_charging_session")
    op.execute("""
        CREATE VIEW semantic_sqlbot_charging.fact_charging_session AS
        SELECT
            session_id, station_id, start_time, end_time, settlement_time,
            charging_duration_seconds, energy_kwh,
            electricity_fee_net_amount, service_fee_net_amount,
            session_status, batch_id, 'simulated'::text AS data_classification
        FROM public.fact_charging_session
    """)
    op.execute("DROP VIEW semantic_sqlbot_charging.dim_station")
    op.execute("""
        CREATE VIEW semantic_sqlbot_charging.dim_station AS
        SELECT
            station_id, station_name, city_id, region_id, operator_code,
            station_type, open_date, connector_count, rated_power_kw, status,
            'simulated'::text AS data_classification
        FROM public.dim_station
    """)
    _restore_role_grants()
