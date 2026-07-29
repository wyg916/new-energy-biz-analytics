import json
from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.auth import AuditLog, User
from app.models.business import DataGenerationRun, Station
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
                "display_name": "\u5145\u7535\u8fd0\u8425",
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
