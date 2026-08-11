"""Merge P6 business-loop and SQLBot 4.1C2 heads for Full Integration 4.1.

Revision ID: integration_41_full_0001
Revises: p6_41_0001, sqlbot_41c2
"""

from alembic import op


revision = "integration_41_full_0001"
down_revision = ("p6_41_0001", "sqlbot_41c2")
branch_labels = None
depends_on = None


def _postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _classification(source_type: str, *, derived: bool = False) -> str:
    if derived:
        return (
            f"CASE WHEN {source_type} = 'open_source' THEN 'OPEN_SOURCE_DERIVED' "
            f"WHEN {source_type} = 'open_derived' THEN 'OPEN_SOURCE_DERIVED' "
            "ELSE 'TEST_FIXTURE' END"
        )
    return (
        f"CASE WHEN {source_type} = 'open_source' THEN 'OPEN_SOURCE_REAL_DATA' "
        f"WHEN {source_type} = 'open_derived' THEN 'OPEN_SOURCE_DERIVED' "
        "ELSE 'TEST_FIXTURE' END"
    )


def _full_classified_views() -> None:
    op.execute(f"""
        CREATE OR REPLACE VIEW semantic_sqlbot_charging.fact_charging_session AS
        SELECT
            s.session_id, s.station_id, s.start_time, s.end_time,
            s.settlement_time, s.charging_duration_seconds, s.energy_kwh,
            s.electricity_fee_net_amount, s.service_fee_net_amount,
            s.session_status, s.batch_id,
            {_classification('s.source_type', derived=True)} AS data_classification,
            s.device_id, s.user_id, u.user_segment
        FROM public.fact_charging_session AS s
        LEFT JOIN public.dim_user AS u ON s.user_id = u.user_id
    """)
    op.execute(f"""
        CREATE OR REPLACE VIEW semantic_sqlbot_charging.dim_station AS
        SELECT
            station_id, station_name, city_id, region_id, operator_code,
            station_type, open_date, connector_count, rated_power_kw, status,
            {_classification('source_type')} AS data_classification,
            operator_code AS operator
        FROM public.dim_station
    """)
    op.execute(f"""
        CREATE OR REPLACE VIEW semantic_sqlbot_charging.fact_energy_cost AS
        SELECT station_id, cost_date, tariff_period, energy_cost, batch_id,
               {_classification('source_type', derived=True)} AS data_classification
        FROM public.fact_energy_cost
    """)
    op.execute(f"""
        CREATE OR REPLACE VIEW semantic_sqlbot_charging.fact_operation_expense AS
        SELECT station_id, expense_date, expense_type, amount, is_variable,
               batch_id, {_classification('source_type', derived=True)} AS data_classification
        FROM public.fact_operation_expense
    """)
    op.execute(f"""
        CREATE OR REPLACE VIEW semantic_sqlbot_charging.fact_device_status_event AS
        SELECT status_event_id, device_id, station_id, status, start_time,
               end_time, batch_id,
               {_classification('source_type')} AS data_classification
        FROM public.fact_device_status_event
    """)


def _sqlbot_41c2_classified_views() -> None:
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
    for relation, projection in (
        (
            "fact_energy_cost",
            "station_id, cost_date, tariff_period, energy_cost, batch_id",
        ),
        (
            "fact_operation_expense",
            "station_id, expense_date, expense_type, amount, is_variable, batch_id",
        ),
        (
            "fact_device_status_event",
            "status_event_id, device_id, station_id, status, start_time, end_time, batch_id",
        ),
    ):
        op.execute(
            f"CREATE OR REPLACE VIEW semantic_sqlbot_charging.{relation} AS "
            f"SELECT {projection}, 'simulated'::text AS data_classification "
            f"FROM public.{relation}"
        )


def upgrade() -> None:
    if _postgresql():
        _full_classified_views()


def downgrade() -> None:
    if _postgresql():
        _sqlbot_41c2_classified_views()
