"""Add scenario-isolated SQLBot semantic schemas and approved views."""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def _postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _postgresql():
        return
    op.execute("CREATE SCHEMA semantic_sqlbot_charging")
    op.execute("REVOKE ALL ON SCHEMA semantic_sqlbot_charging FROM PUBLIC")
    op.execute("""
        CREATE VIEW semantic_sqlbot_charging.active_context AS
        SELECT
            a.tenant_id,
            a.workspace_id,
            a.scenario_id,
            a.scenario_version,
            a.active_dataset_version_id AS dataset_version_id,
            dv.version AS dataset_version,
            a.active_semantic_model_version_id AS semantic_model_version_id,
            smv.version AS semantic_version,
            a.activated_at
        FROM public.semantic_activation a
        JOIN public.dataset_version dv
          ON dv.dataset_version_id = a.active_dataset_version_id
         AND dv.status = 'ACTIVE'
        JOIN public.semantic_model_version smv
          ON smv.semantic_model_version_id = a.active_semantic_model_version_id
         AND smv.status = 'ACTIVE'
        WHERE a.scenario_id = 'charging_ops'
    """)
    op.execute("""
        CREATE VIEW semantic_sqlbot_charging.dim_station AS
        SELECT
            station_id, station_name, city_id, region_id, operator_code,
            station_type, open_date, connector_count, rated_power_kw, status,
            'simulated'::text AS data_classification
        FROM public.dim_station
    """)
    op.execute("""
        CREATE VIEW semantic_sqlbot_charging.fact_charging_session AS
        SELECT
            session_id, station_id, start_time, end_time, settlement_time,
            charging_duration_seconds, energy_kwh,
            electricity_fee_net_amount, service_fee_net_amount,
            session_status, batch_id, 'simulated'::text AS data_classification
        FROM public.fact_charging_session
    """)

    op.execute("CREATE SCHEMA semantic_sqlbot_sales")
    op.execute("REVOKE ALL ON SCHEMA semantic_sqlbot_sales FROM PUBLIC")
    op.execute("""
        CREATE VIEW semantic_sqlbot_sales.active_context AS
        SELECT
            a.tenant_id,
            a.workspace_id,
            a.scenario_id,
            a.scenario_version,
            a.active_dataset_version_id AS dataset_version_id,
            dv.version AS dataset_version,
            a.active_semantic_model_version_id AS semantic_model_version_id,
            smv.version AS semantic_version,
            a.activated_at
        FROM public.semantic_activation a
        JOIN public.dataset_version dv
          ON dv.dataset_version_id = a.active_dataset_version_id
         AND dv.status = 'ACTIVE'
        JOIN public.semantic_model_version smv
          ON smv.semantic_model_version_id = a.active_semantic_model_version_id
         AND smv.status = 'ACTIVE'
        WHERE a.scenario_id = 'sales_ops'
    """)
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
        CREATE VIEW semantic_sqlbot_sales.sales_order_item AS
        SELECT
            order_item_id, order_id, line_number, product_id, quantity,
            unit_price, gross_amount, discount_amount, refund_amount,
            net_revenue, cost_amount, gross_profit, data_classification,
            seed_run_id
        FROM public.sales_order_item
    """)
    op.execute("""
        CREATE VIEW semantic_sqlbot_sales.sales_region AS
        SELECT region_id, region_name, organization_code, data_classification
        FROM public.sales_region
    """)
    op.execute("""
        CREATE VIEW semantic_sqlbot_sales.sales_channel AS
        SELECT channel_id, channel_name, channel_type, data_classification
        FROM public.sales_channel
    """)
    op.execute("""
        CREATE VIEW semantic_sqlbot_sales.sales_product AS
        SELECT
            product_id, product_name, category_id, list_price, standard_cost,
            data_classification
        FROM public.sales_product
    """)


def downgrade() -> None:
    if not _postgresql():
        return
    op.execute("DROP SCHEMA semantic_sqlbot_sales CASCADE")
    op.execute("DROP SCHEMA semantic_sqlbot_charging CASCADE")
