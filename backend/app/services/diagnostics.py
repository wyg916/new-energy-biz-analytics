import json
import statistics
from datetime import date
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.auth import AuditLog, User
from app.models.business import DataGenerationRun, Station
from app.services.dashboard import allowed_station_ids
from app.services.metric_catalog import METRICS
from app.scenarios.registry import published_charging_ops_batch
from app.services.metrics import MetricService


def comparison_period(start: date, end_exclusive: date, comparison: str) -> tuple[date, date]:
    if comparison == "yoy":
        return start.replace(year=start.year - 1), end_exclusive.replace(year=end_exclusive.year - 1)
    next_month = date(start.year + (start.month == 12), 1 if start.month == 12 else start.month + 1, 1)
    if start.day == 1 and end_exclusive == next_month:
        previous_start = date(start.year - (start.month == 1), 12 if start.month == 1 else start.month - 1, 1)
        return previous_start, start
    duration = end_exclusive - start
    return start - duration, start


class DiagnosticService:
    def __init__(self, db: Session, user: User):
        self.db = db; self.user = user; self.station_ids = allowed_station_ids(db, user)

    def _metadata(self, run_id: str, start: date, end: date, previous_start: date, previous_end: date) -> dict:
        batch = published_charging_ops_batch(self.db)
        return {"analysis_run_id": run_id, "data_classification": "simulated", "source": "platform_database", "batch_id": batch.batch_id if batch else None, "current_period": [start.isoformat(), end.isoformat()], "comparison_period": [previous_start.isoformat(), previous_end.isoformat()], "causality_boundary": "关联因素说明，不构成因果结论"}

    def _audit(self, run_id: str, action: str, detail: dict) -> None:
        self.db.add(AuditLog(actor_user_id=self.user.id, action=action, resource="diagnostics", outcome="success", detail_json=json.dumps({"analysis_run_id": run_id, **detail})))
        self.db.commit()

    def decompose(self, metric_id: str, start: date, end_exclusive: date, comparison: str = "mom", limit: int = 5) -> dict:
        if metric_id not in {"charging_revenue", "gross_profit"}:
            raise ValueError("only revenue and gross profit support decomposition")
        previous_start, previous_end = comparison_period(start, end_exclusive, comparison)
        metric_ids = ["charging_revenue", "charging_volume_kwh", "revenue_per_kwh", "energy_cost", "variable_operating_cost", "gross_profit", "device_online_rate", "device_fault_rate"]
        service = MetricService(self.db)
        current = service.compute(metric_ids, start, end_exclusive, self.station_ids)
        previous = service.compute(metric_ids, previous_start, previous_end, self.station_ids)
        changes = {key: round((current[key] or 0) - (previous[key] or 0), 6) for key in metric_ids}
        if metric_id == "charging_revenue":
            volume_effect = round(((current["charging_volume_kwh"] or 0) - (previous["charging_volume_kwh"] or 0)) * (previous["revenue_per_kwh"] or 0), 6)
            price_effect = round((current["charging_volume_kwh"] or 0) * ((current["revenue_per_kwh"] or 0) - (previous["revenue_per_kwh"] or 0)), 6)
            residual = round(changes["charging_revenue"] - volume_effect - price_effect, 6)
            bridge = [{"driver": "charging_volume_effect", "contribution": volume_effect}, {"driver": "revenue_per_kwh_effect", "contribution": price_effect}, {"driver": "rounding_residual", "contribution": residual}]
        else:
            bridge = [
                {"driver": "charging_revenue_change", "contribution": changes["charging_revenue"]},
                {"driver": "energy_cost_change", "contribution": -changes["energy_cost"]},
                {"driver": "variable_operating_cost_change", "contribution": -changes["variable_operating_cost"]},
            ]
        stations = self.db.scalars(select(Station).where(Station.station_id.in_(self.station_ids)).order_by(Station.station_id)).all()
        contributions = []
        for station in stations:
            current_value = service.compute([metric_id], start, end_exclusive, [station.station_id])[metric_id] or 0
            previous_value = service.compute([metric_id], previous_start, previous_end, [station.station_id])[metric_id] or 0
            contributions.append({"station_id": station.station_id, "station_name": station.station_name, "region_id": station.region_id, "current": current_value, "previous": previous_value, "contribution": round(current_value - previous_value, 6)})
        contributions.sort(key=lambda item: abs(item["contribution"]), reverse=True)
        run_id = f"DIAG-{uuid4()}"
        related = [
            {"factor": "device_online_rate", "change": changes["device_online_rate"], "statement": "设备在线率与经营变化同期变动，仅作为关联线索。"},
            {"factor": "device_fault_rate", "change": changes["device_fault_rate"], "statement": "设备故障率与经营变化同期变动，不据此宣称因果。"},
        ]
        result = {"metric_id": metric_id, "comparison": comparison, "current": current, "previous": previous, "changes": changes, "bridge": bridge, "station_contributions": contributions[:limit], "related_factors": related, "reconciliation": {"target_change": changes[metric_id], "bridge_sum": round(sum(item["contribution"] for item in bridge), 6), "residual": round(changes[metric_id] - sum(item["contribution"] for item in bridge), 6)}, "metadata": self._metadata(run_id, start, end_exclusive, previous_start, previous_end)}
        self._audit(run_id, "diagnostics.decompose", {"metric_id": metric_id, "comparison": comparison})
        return result

    def anomalies(self, metric_id: str, start: date, end_exclusive: date, threshold: float = 0.15) -> dict:
        if metric_id not in METRICS:
            raise ValueError("unknown metric")
        previous_start, previous_end = comparison_period(start, end_exclusive, "mom")
        service = MetricService(self.db)
        current = service.compute([metric_id], start, end_exclusive, self.station_ids)[metric_id]
        previous = service.compute([metric_id], previous_start, previous_end, self.station_ids)[metric_id]
        change_rate = None if previous in (None, 0) or current is None else round((current - previous) / abs(previous), 6)
        triggered = change_rate is not None and abs(change_rate) >= threshold
        run_id = f"ANOM-{uuid4()}"
        result = {"metric_id": metric_id, "rule": {"type": "mom_change", "threshold": threshold, "direction": "both"}, "current": current, "previous": previous, "change_rate": change_rate, "triggered": triggered, "severity": "high" if triggered and abs(change_rate) >= threshold * 2 else "medium" if triggered else "none", "metadata": self._metadata(run_id, start, end_exclusive, previous_start, previous_end)}
        self._audit(run_id, "diagnostics.anomaly", {"metric_id": metric_id, "triggered": triggered})
        return result

    def peer_comparison(self, station_id: str, metric_id: str, start: date, end_exclusive: date) -> dict:
        if station_id not in self.station_ids or metric_id not in METRICS:
            raise PermissionError("station or metric not allowed")
        service = MetricService(self.db)
        values = [(candidate, service.compute([metric_id], start, end_exclusive, [candidate])[metric_id]) for candidate in self.station_ids]
        numeric = [value for _, value in values if value is not None]
        station_value = dict(values)[station_id]
        median = statistics.median(numeric) if numeric else None
        percentile = None if station_value is None or not numeric else round(sum(value <= station_value for value in numeric) / len(numeric), 4)
        run_id = f"PEER-{uuid4()}"
        return {"station_id": station_id, "metric_id": metric_id, "value": station_value, "peer_median": median, "peer_percentile": percentile, "peer_count": len(numeric), "metadata": {"analysis_run_id": run_id, "data_classification": "simulated", "source": "platform_database", "causality_boundary": "同群差异不等于因果"}}
