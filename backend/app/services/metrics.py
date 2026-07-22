from datetime import date, datetime, time, timezone
from decimal import Decimal

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.models.business import ChargingSession, DeviceStatusEvent, EnergyCost, OperationExpense, Station
from app.services.metric_catalog import METRICS


def _decimal(value) -> Decimal:
    return Decimal(str(value or 0))


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    return None if denominator == 0 else numerator / denominator


class MetricService:
    def __init__(self, db: Session):
        self.db = db

    def compute(self, metric_ids: list[str], start: date, end_exclusive: date, station_ids: list[str] | None = None) -> dict[str, float | int | None]:
        unknown = sorted(set(metric_ids) - METRICS.keys())
        if unknown:
            raise ValueError(f"unknown metric: {','.join(unknown)}")
        start_dt = datetime.combine(start, time.min, timezone.utc)
        end_dt = datetime.combine(end_exclusive, time.min, timezone.utc)
        session_filters = [ChargingSession.session_status == "completed", ChargingSession.settlement_time >= start_dt, ChargingSession.settlement_time < end_dt]
        cost_filters = [EnergyCost.cost_date >= start, EnergyCost.cost_date < end_exclusive]
        expense_filters = [OperationExpense.expense_date >= start, OperationExpense.expense_date < end_exclusive, OperationExpense.is_variable.is_(True)]
        if station_ids:
            session_filters.append(ChargingSession.station_id.in_(station_ids))
            cost_filters.append(EnergyCost.station_id.in_(station_ids))
            expense_filters.append(OperationExpense.station_id.in_(station_ids))

        session_row = self.db.execute(select(
            func.coalesce(func.sum(ChargingSession.electricity_fee_net_amount + ChargingSession.service_fee_net_amount), 0),
            func.coalesce(func.sum(ChargingSession.service_fee_net_amount), 0),
            func.count(distinct(ChargingSession.session_id)),
            func.coalesce(func.sum(ChargingSession.energy_kwh), 0),
            func.coalesce(func.sum(ChargingSession.charging_duration_seconds), 0),
            func.count(distinct(ChargingSession.user_id)),
        ).where(*session_filters)).one()
        charging_revenue, service_revenue, order_count, volume, duration, active_users = map(_decimal, session_row)
        energy_cost = _decimal(self.db.scalar(select(func.coalesce(func.sum(EnergyCost.energy_cost), 0)).where(*cost_filters)))
        variable_cost = _decimal(self.db.scalar(select(func.coalesce(func.sum(OperationExpense.amount), 0)).where(*expense_filters)))
        gross_profit = charging_revenue - energy_cost - variable_cost

        station_query = select(func.coalesce(func.sum(Station.connector_count), 0))
        if station_ids:
            station_query = station_query.where(Station.station_id.in_(station_ids))
        connector_count = _decimal(self.db.scalar(station_query))
        available_seconds = connector_count * Decimal((end_dt - start_dt).total_seconds())

        event_filters = [DeviceStatusEvent.start_time < end_dt, DeviceStatusEvent.end_time > start_dt, DeviceStatusEvent.status != "unknown"]
        if station_ids:
            event_filters.append(DeviceStatusEvent.station_id.in_(station_ids))
        events = self.db.execute(select(DeviceStatusEvent.status, DeviceStatusEvent.start_time, DeviceStatusEvent.end_time).where(*event_filters)).all()
        observable = online = fault = Decimal(0)
        for status, event_start, event_end in events:
            event_start = event_start.replace(tzinfo=timezone.utc) if event_start.tzinfo is None else event_start
            event_end = event_end.replace(tzinfo=timezone.utc) if event_end.tzinfo is None else event_end
            seconds = Decimal((min(event_end, end_dt) - max(event_start, start_dt)).total_seconds())
            observable += max(seconds, Decimal(0))
            if status == "online": online += max(seconds, Decimal(0))
            if status == "fault": fault += max(seconds, Decimal(0))

        values = {
            "charging_revenue": charging_revenue,
            "service_fee_revenue": service_revenue,
            "completed_order_count": order_count,
            "charging_volume_kwh": volume,
            "energy_cost": energy_cost,
            "variable_operating_cost": variable_cost,
            "gross_profit": gross_profit,
            "gross_margin": _ratio(gross_profit, charging_revenue),
            "avg_order_energy_kwh": _ratio(volume, order_count),
            "revenue_per_kwh": _ratio(charging_revenue, volume),
            "cost_per_kwh": _ratio(energy_cost + variable_cost, volume),
            "station_utilization_rate": _ratio(duration, available_seconds),
            "device_online_rate": _ratio(online, observable),
            "device_fault_rate": _ratio(fault, observable),
            "active_user_count": active_users,
        }
        return {metric_id: (None if values[metric_id] is None else int(values[metric_id]) if metric_id in {"completed_order_count", "active_user_count"} else round(float(values[metric_id]), 6)) for metric_id in metric_ids}
