import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.auth import AuditLog, User
from app.models.business import ChargingSession, City, Region, Station
from app.services.dashboard import DashboardService, allowed_station_ids


SHANGHAI = ZoneInfo("Asia/Shanghai")


class RevenueAnalysisService:
    """Read-only, deterministic aggregations for the revenue-and-orders workspace."""

    def __init__(self, db: Session, user: User):
        self.db = db
        self.user = user
        self.station_ids = allowed_station_ids(db, user)

    @staticmethod
    def _business_time(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=SHANGHAI)
        return value.astimezone(SHANGHAI)

    def analysis(self, start: date, end_exclusive: date) -> dict:
        run_id = f"REV-{uuid4()}"
        stations = {
            station.station_id: station
            for station in self.db.scalars(
                select(Station).where(Station.station_id.in_(self.station_ids))
            ).all()
        }
        regions = {
            item.region_id: item.region_name
            for item in self.db.scalars(select(Region)).all()
        }
        cities = {
            item.city_id: item.city_name
            for item in self.db.scalars(select(City)).all()
        }
        city_regions = {station.city_id: station.region_id for station in stations.values()}
        # Keep the fact-selection boundary identical to MetricService so every
        # displayed breakdown reconciles to the published charging_revenue KPI.
        start_at = datetime.combine(start, datetime.min.time())
        end_at = datetime.combine(end_exclusive, datetime.min.time())
        rows = self.db.execute(
            select(
                ChargingSession.station_id,
                ChargingSession.settlement_time,
                ChargingSession.electricity_fee_net_amount,
                ChargingSession.service_fee_net_amount,
            ).where(
                ChargingSession.station_id.in_(self.station_ids),
                ChargingSession.session_status == "completed",
                ChargingSession.settlement_time >= start_at,
                ChargingSession.settlement_time < end_at,
            )
        ).all()

        daily: dict[date, float] = defaultdict(float)
        heatmap: dict[tuple[int, int], float] = defaultdict(float)
        region_values: dict[str, float] = defaultdict(float)
        city_values: dict[str, float] = defaultdict(float)
        for station_id, settled_at, electricity_fee, service_fee in rows:
            if settled_at is None:
                continue
            business_time = self._business_time(settled_at)
            revenue = float(electricity_fee + service_fee)
            station = stations.get(station_id)
            daily[business_time.date()] += revenue
            heatmap[(business_time.weekday() + 1, business_time.hour)] += revenue
            if station:
                region_values[station.region_id] += revenue
                city_values[station.city_id] += revenue

        current = start
        daily_points = []
        while current < end_exclusive:
            daily_points.append({"period": current.isoformat(), "value": round(daily[current], 2)})
            current += timedelta(days=1)

        region_rows = sorted(region_values.items(), key=lambda item: (-item[1], item[0]))
        city_rows = sorted(city_values.items(), key=lambda item: (-item[1], item[0]))
        metadata = DashboardService(self.db, self.user)._metadata(start, end_exclusive, run_id)
        self.db.add(
            AuditLog(
                actor_user_id=self.user.id,
                action="revenue.analysis",
                resource="revenue",
                outcome="success",
                detail_json=json.dumps(
                    {
                        "analysis_run_id": run_id,
                        "start": start.isoformat(),
                        "end_exclusive": end_exclusive.isoformat(),
                        "station_count": len(self.station_ids),
                        "session_count": len(rows),
                    }
                ),
            )
        )
        self.db.commit()
        return {
            "daily_trend": daily_points,
            "heatmap": [
                {"weekday": weekday, "hour": hour, "value": round(heatmap[(weekday, hour)], 2)}
                for weekday in range(1, 8)
                for hour in range(24)
            ],
            "regions": [
                {"region_id": region_id, "region_name": regions.get(region_id, region_id), "value": round(value, 2)}
                for region_id, value in region_rows
            ],
            "cities": [
                {
                    "city_id": city_id,
                    "city_name": cities.get(city_id, city_id),
                    "region_id": city_regions.get(city_id, ""),
                    "value": round(value, 2),
                }
                for city_id, value in city_rows
            ],
            "metadata": metadata,
        }
