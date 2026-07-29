import json
from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.auth import AuditLog, User
from app.models.business import ChargingSession, DataGenerationRun, Device, DeviceStatusEvent, Station
from app.models.business import MetricDefinition
from app.services.metric_catalog import METRICS
from app.services.metrics import MetricService


def allowed_station_ids(db: Session, user: User) -> list[str]:
    query = select(Station.station_id).where(Station.status == "active")
    if user.role == "regional_manager":
        if not user.region_code:
            return []
        query = query.where(Station.region_id == user.region_code)
    return list(db.scalars(query.order_by(Station.station_id)).all())


class DashboardService:
    def __init__(self, db: Session, user: User):
        self.db = db
        self.user = user
        self.station_ids = allowed_station_ids(db, user)

    def _metadata(self, start: date, end_exclusive: date, analysis_run_id: str) -> dict:
        batch = self.db.scalar(select(DataGenerationRun).where(DataGenerationRun.quality_status == "passed").order_by(DataGenerationRun.finished_at.desc()))
        return {
            "data_classification": "simulated",
            "data_time_range": {"start": start.isoformat(), "end_exclusive": end_exclusive.isoformat()},
            "source": "platform_database",
            "batch_id": batch.batch_id if batch else None,
            "analysis_run_id": analysis_run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _audit(self, action: str, run_id: str, detail: dict) -> None:
        self.db.add(AuditLog(actor_user_id=self.user.id, action=action, resource="dashboard", outcome="success", detail_json=json.dumps({"analysis_run_id": run_id, **detail})))
        self.db.commit()

    def summary(self, start: date, end_exclusive: date) -> dict:
        run_id = f"DASH-{uuid4()}"
        metrics = MetricService(self.db).compute(list(METRICS), start, end_exclusive, self.station_ids)
        self._audit("dashboard.summary", run_id, {"start": start.isoformat(), "end_exclusive": end_exclusive.isoformat(), "station_count": len(self.station_ids)})
        return {"metrics": metrics, "metadata": self._metadata(start, end_exclusive, run_id)}

    def metric_catalog(self, start: date, end_exclusive: date) -> dict:
        run_id = f"DASH-{uuid4()}"
        definitions = self.db.scalars(
            select(MetricDefinition).order_by(MetricDefinition.metric_id)
        ).all()
        rows = [{
            "metric_id": definition.metric_id,
            "display_name": definition.display_name,
            "unit": definition.unit,
            "version": definition.version,
            "status": definition.status,
            "formula": definition.formula,
            "allowed_dimensions": json.loads(definition.allowed_dimensions_json),
        } for definition in definitions]
        self._audit(
            "dashboard.metric_catalog",
            run_id,
            {
                "start": start.isoformat(),
                "end_exclusive": end_exclusive.isoformat(),
                "metric_count": len(rows),
            },
        )
        return {
            "rows": rows,
            "scenario": {
                "scenario_id": "charging_ops",
                "display_name": "充电运营",
                "status": "approved_for_implementation",
            },
            "metadata": self._metadata(start, end_exclusive, run_id),
        }

    def station_analysis(self, metric_ids: list[str], start: date, end_exclusive: date, limit: int = 30) -> dict:
        run_id = f"DASH-{uuid4()}"
        stations = self.db.scalars(select(Station).where(Station.station_id.in_(self.station_ids)).order_by(Station.station_id)).all()
        rows = []
        metric_service = MetricService(self.db)
        for station in stations:
            values = metric_service.compute(metric_ids, start, end_exclusive, [station.station_id])
            rows.append({"station_id": station.station_id, "station_name": station.station_name, "region_id": station.region_id, "city_id": station.city_id, "station_type": station.station_type, "metrics": values})
        primary = metric_ids[0]
        rows.sort(key=lambda row: (row["metrics"][primary] is not None, row["metrics"][primary] or 0), reverse=True)
        self._audit("dashboard.station_analysis", run_id, {"metrics": metric_ids, "start": start.isoformat(), "end_exclusive": end_exclusive.isoformat()})
        return {"rows": rows[:limit], "metadata": self._metadata(start, end_exclusive, run_id)}

    def device_analysis(self, start: date, end_exclusive: date, limit: int = 120) -> dict:
        run_id = f"DASH-{uuid4()}"
        start_at = datetime.combine(start, datetime.min.time())
        end_at = datetime.combine(end_exclusive, datetime.min.time())
        devices = self.db.execute(
            select(Device, Station.station_name, Station.region_id)
            .join(Station, Device.station_id == Station.station_id)
            .where(Device.station_id.in_(self.station_ids), Device.status == "active")
            .order_by(Device.device_id)
        ).all()
        events = self.db.scalars(
            select(DeviceStatusEvent)
            .where(
                DeviceStatusEvent.station_id.in_(self.station_ids),
                DeviceStatusEvent.start_time < end_at,
                DeviceStatusEvent.end_time > start_at,
            )
            .order_by(DeviceStatusEvent.device_id, DeviceStatusEvent.start_time)
        ).all()
        event_map: dict[str, list[DeviceStatusEvent]] = {}
        reason_summary: dict[str, int] = {}
        for event in events:
            event_map.setdefault(event.device_id, []).append(event)
            if event.status != "online":
                reason = event.reason_code or ("PLANNED_MAINTENANCE" if event.is_planned else event.status.upper())
                reason_summary[reason] = reason_summary.get(reason, 0) + 1

        session_rows = self.db.execute(
            select(
                ChargingSession.device_id,
                func.count(ChargingSession.session_id),
                func.coalesce(func.sum(ChargingSession.electricity_fee_net_amount + ChargingSession.service_fee_net_amount), 0),
            )
            .where(
                ChargingSession.station_id.in_(self.station_ids),
                ChargingSession.session_status == "completed",
                ChargingSession.settlement_time >= start_at,
                ChargingSession.settlement_time < end_at,
            )
            .group_by(ChargingSession.device_id)
        ).all()
        sessions = {device_id: {"order_count": int(order_count), "charging_revenue": float(revenue)} for device_id, order_count, revenue in session_rows}

        rows = []
        totals = {"device_count": len(devices), "online_count": 0, "offline_count": 0, "fault_count": 0, "risk_order_count": 0, "risk_revenue": 0.0}
        aggregate_durations = {"online": 0.0, "offline": 0.0, "fault": 0.0}
        for device, station_name, region_id in devices:
            device_events = event_map.get(device.device_id, [])
            durations = {"online": 0.0, "offline": 0.0, "fault": 0.0, "unknown": 0.0}
            for event in device_events:
                start_bound = start_at.replace(tzinfo=event.start_time.tzinfo)
                end_bound = end_at.replace(tzinfo=event.end_time.tzinfo)
                event_start = max(event.start_time, start_bound)
                event_end = min(event.end_time, end_bound)
                durations[event.status] = durations.get(event.status, 0.0) + max((event_end - event_start).total_seconds(), 0) / 3600
            latest = device_events[-1] if device_events else None
            current_status = latest.status if latest else "unknown"
            status_key = f"{current_status}_count"
            if status_key in totals:
                totals[status_key] += 1
            observable = durations["online"] + durations["offline"] + durations["fault"]
            for status in aggregate_durations:
                aggregate_durations[status] += durations[status]
            fault_rate = durations["fault"] / observable if observable else None
            related = sessions.get(device.device_id, {"order_count": 0, "charging_revenue": 0.0})
            if current_status in {"fault", "offline"}:
                totals["risk_order_count"] += related["order_count"]
                totals["risk_revenue"] += related["charging_revenue"]
            priority = "P1" if current_status == "fault" else "P2" if current_status == "offline" or (fault_rate or 0) >= .03 else "P4"
            rows.append({
                "device_id": device.device_id,
                "station_id": device.station_id,
                "station_name": station_name,
                "region_id": region_id,
                "device_model": device.device_model,
                "connector_count": device.connector_count,
                "rated_power_kw": float(device.rated_power_kw),
                "commission_date": device.commission_date.isoformat(),
                "current_status": current_status,
                "priority": priority,
                "online_hours": round(durations["online"], 2),
                "offline_hours": round(durations["offline"], 2),
                "fault_hours": round(durations["fault"], 2),
                "fault_event_count": sum(1 for event in device_events if event.status == "fault"),
                "fault_rate": fault_rate,
                "related_order_count": related["order_count"],
                "related_revenue": related["charging_revenue"],
                "recent_events": [{
                    "status": event.status,
                    "reason_code": event.reason_code,
                    "is_planned": event.is_planned,
                    "start_time": event.start_time.isoformat(),
                    "end_time": event.end_time.isoformat(),
                    "duration_hours": round((event.end_time - event.start_time).total_seconds() / 3600, 2),
                } for event in reversed(device_events[-4:])],
            })
        rows.sort(key=lambda row: (row["priority"], -(row["fault_hours"] + row["offline_hours"]), row["device_id"]))
        reasons = [{"reason_code": code, "count": count} for code, count in sorted(reason_summary.items(), key=lambda item: (-item[1], item[0]))]
        observable_hours = sum(aggregate_durations.values())
        metrics = {
            "device_online_rate": aggregate_durations["online"] / observable_hours if observable_hours else None,
            "device_fault_rate": aggregate_durations["fault"] / observable_hours if observable_hours else None,
        }
        self._audit("dashboard.device_analysis", run_id, {"start": start.isoformat(), "end_exclusive": end_exclusive.isoformat(), "device_count": len(devices)})
        return {"rows": rows[:limit], "totals": totals, "metrics": metrics, "reason_summary": reasons, "metadata": self._metadata(start, end_exclusive, run_id)}

    def monthly_trend(self, metric_id: str, start: date, end_exclusive: date) -> dict:
        run_id = f"DASH-{uuid4()}"
        points = []
        current = date(start.year, start.month, 1)
        service = MetricService(self.db)
        while current < end_exclusive:
            next_month = date(current.year + (current.month == 12), 1 if current.month == 12 else current.month + 1, 1)
            period_start = max(start, current)
            period_end = min(end_exclusive, next_month)
            points.append({"period": current.strftime("%Y-%m"), "value": service.compute([metric_id], period_start, period_end, self.station_ids)[metric_id]})
            current = next_month
        self._audit("dashboard.trend", run_id, {"metric": metric_id, "start": start.isoformat(), "end_exclusive": end_exclusive.isoformat()})
        return {"metric_id": metric_id, "points": points, "metadata": self._metadata(start, end_exclusive, run_id)}
