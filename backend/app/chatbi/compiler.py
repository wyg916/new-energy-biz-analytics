from dataclasses import dataclass
from datetime import datetime, time, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chatbi.plan import QueryPlan
from app.models.business import Station


class ScopeDenied(PermissionError):
    pass


@dataclass(frozen=True)
class CompiledQuery:
    sql: str
    parameters: dict
    metric_ids: list[str]
    station_ids: list[str]


EXPRESSIONS = {
    "charging_revenue": "s.charging_revenue",
    "service_fee_revenue": "s.service_fee_revenue",
    "completed_order_count": "s.completed_order_count",
    "charging_volume_kwh": "s.charging_volume_kwh",
    "energy_cost": "e.energy_cost",
    "variable_operating_cost": "o.variable_operating_cost",
    "gross_profit": "s.charging_revenue - e.energy_cost - o.variable_operating_cost",
    "gross_margin": "(s.charging_revenue - e.energy_cost - o.variable_operating_cost) / NULLIF(CAST(s.charging_revenue AS FLOAT), 0)",
    "avg_order_energy_kwh": "s.charging_volume_kwh / NULLIF(CAST(s.completed_order_count AS FLOAT), 0)",
    "revenue_per_kwh": "s.charging_revenue / NULLIF(CAST(s.charging_volume_kwh AS FLOAT), 0)",
    "cost_per_kwh": "(e.energy_cost + o.variable_operating_cost) / NULLIF(CAST(s.charging_volume_kwh AS FLOAT), 0)",
    "station_utilization_rate": "s.charging_duration / NULLIF(CAST(st.connector_count * :period_seconds AS FLOAT), 0)",
    "device_online_rate": "ds.online_count / NULLIF(CAST(ds.observable_count AS FLOAT), 0)",
    "device_fault_rate": "ds.fault_count / NULLIF(CAST(ds.observable_count AS FLOAT), 0)",
    "active_user_count": "s.active_user_count",
}


def _requested_scope(db: Session, plan: QueryPlan, authorized_station_ids: list[str]) -> list[str]:
    requested = set(authorized_station_ids)
    for item in plan.filters:
        values = item.value if isinstance(item.value, list) else [item.value]
        if item.field == "region":
            region_map = {"区域A": "R01", "区域B": "R02", "区域C": "R03"}
            region_ids = [region_map.get(value, value) for value in values]
            found = set(db.scalars(select(Station.station_id).where(Station.region_id.in_(region_ids))).all())
            requested &= found
        elif item.field == "station":
            station_map = {f"场站A{i:02d}": f"S{i:03d}" for i in range(1, 31)}
            requested &= {station_map.get(value, value) for value in values}
    if not requested:
        raise ScopeDenied("requested scope has no authorized intersection")
    return sorted(requested)


def compile_query(db: Session, plan: QueryPlan, authorized_station_ids: list[str]) -> CompiledQuery:
    if plan.status != "ready" or plan.time_range is None:
        raise ValueError("only ready plans can be compiled")
    station_ids = _requested_scope(db, plan, authorized_station_ids)
    station_placeholders = ", ".join(f":station_{index}" for index in range(len(station_ids)))
    expressions = ", ".join(f"{EXPRESSIONS[metric_id]} AS {metric_id}" for metric_id in plan.metrics)
    sql = f"""WITH s AS (
      SELECT COALESCE(SUM(electricity_fee_net_amount + service_fee_net_amount), 0) AS charging_revenue,
             COALESCE(SUM(service_fee_net_amount), 0) AS service_fee_revenue,
             COUNT(DISTINCT session_id) AS completed_order_count,
             COALESCE(SUM(energy_kwh), 0) AS charging_volume_kwh,
             COALESCE(SUM(charging_duration_seconds), 0) AS charging_duration,
             COUNT(DISTINCT user_id) AS active_user_count
      FROM fact_charging_session
      WHERE session_status = 'completed' AND settlement_time >= :start_ts AND settlement_time < :end_ts
        AND station_id IN ({station_placeholders})
    ), e AS (
      SELECT COALESCE(SUM(energy_cost), 0) AS energy_cost FROM fact_energy_cost
      WHERE cost_date >= :start_date AND cost_date < :end_date AND station_id IN ({station_placeholders})
    ), o AS (
      SELECT COALESCE(SUM(amount), 0) AS variable_operating_cost FROM fact_operation_expense
      WHERE is_variable = TRUE AND expense_date >= :start_date AND expense_date < :end_date AND station_id IN ({station_placeholders})
    ), st AS (
      SELECT COALESCE(SUM(connector_count), 0) AS connector_count FROM dim_station WHERE station_id IN ({station_placeholders})
    ), ds AS (
      SELECT SUM(CASE WHEN status = 'online' THEN 1 ELSE 0 END) AS online_count,
             SUM(CASE WHEN status = 'fault' THEN 1 ELSE 0 END) AS fault_count,
             SUM(CASE WHEN status != 'unknown' THEN 1 ELSE 0 END) AS observable_count
      FROM fact_device_status_event
      WHERE start_time >= :start_ts AND start_time < :end_ts AND station_id IN ({station_placeholders})
    ) SELECT {expressions} FROM s CROSS JOIN e CROSS JOIN o CROSS JOIN st CROSS JOIN ds LIMIT :limit"""
    period = plan.time_range
    start_dt = datetime.combine(period.start, time.min, timezone.utc)
    end_dt = datetime.combine(period.end_exclusive, time.min, timezone.utc)
    parameters = {"start_ts": start_dt, "end_ts": end_dt, "start_date": period.start, "end_date": period.end_exclusive, "period_seconds": int((end_dt - start_dt).total_seconds()), "limit": min(plan.limit, 5000)}
    parameters.update({f"station_{index}": station_id for index, station_id in enumerate(station_ids)})
    return CompiledQuery(sql=sql, parameters=parameters, metric_ids=plan.metrics, station_ids=station_ids)
