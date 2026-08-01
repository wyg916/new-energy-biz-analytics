from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from sqlalchemy.orm import Session

from app.models.auth import User
from app.scenarios.sales_ops.metrics import SALES_METRICS, SalesOpsMetricService
from app.services.dashboard import DashboardService, allowed_station_ids
from app.services.diagnostics import DiagnosticService
from app.services.metric_catalog import METRICS
from app.services.metrics import MetricService


def previous_period(start: date, end_exclusive: date, comparison: str) -> tuple[date, date]:
    if comparison == "yoy":
        return start.replace(year=start.year - 1), end_exclusive.replace(year=end_exclusive.year - 1)
    duration = end_exclusive - start
    return start - duration, start


class AnalysisAdapter(Protocol):
    scenario_id: str
    revenue_metric: str
    order_metric: str
    gross_profit_metric: str
    efficiency_metric: str | None
    default_dimension: str

    def metrics(self, start: date, end_exclusive: date, metric_ids: tuple[str, ...]) -> dict: ...
    def breakdown(self, start: date, end_exclusive: date, metric_id: str, dimension: str, limit: int) -> tuple[dict, ...]: ...
    def drivers(self, skill_code: str, start: date, end_exclusive: date, comparison: str) -> tuple[dict, ...]: ...
    def metric_metadata(self, metric_id: str) -> dict: ...
    def report_metrics(self) -> tuple[str, ...]: ...


@dataclass
class ChargingOpsAnalysisAdapter:
    db: Session
    user: User
    scenario_id: str = "charging_ops"
    revenue_metric: str = "charging_revenue"
    order_metric: str = "order_count"
    gross_profit_metric: str = "gross_profit"
    efficiency_metric: str = "station_utilization_rate"
    default_dimension: str = "station"

    def metrics(self, start: date, end_exclusive: date, metric_ids: tuple[str, ...]) -> dict:
        return MetricService(self.db).compute(
            list(metric_ids), start, end_exclusive, allowed_station_ids(self.db, self.user)
        )

    def breakdown(
        self,
        start: date,
        end_exclusive: date,
        metric_id: str,
        dimension: str,
        limit: int,
    ) -> tuple[dict, ...]:
        rows = DashboardService(self.db, self.user).station_analysis(
            [metric_id], start, end_exclusive, limit=50
        )["rows"]
        if dimension == "station":
            return tuple({
                "dimension": row["station_id"],
                "dimension_name": row["station_name"],
                "value": row["metrics"][metric_id],
            } for row in rows[:limit])
        if dimension == "region":
            grouped: dict[str, float] = {}
            for row in rows:
                value = row["metrics"][metric_id]
                if value is not None:
                    grouped[row["region_id"]] = grouped.get(row["region_id"], 0.0) + float(value)
            return tuple({
                "dimension": key,
                "dimension_name": key,
                "value": round(value, 6),
            } for key, value in sorted(grouped.items(), key=lambda item: abs(item[1]), reverse=True)[:limit])
        raise ValueError("charging_ops analysis dimension is not supported")

    def drivers(
        self,
        skill_code: str,
        start: date,
        end_exclusive: date,
        comparison: str,
    ) -> tuple[dict, ...]:
        metric = self.gross_profit_metric if skill_code == "gross_profit_change_decomposition" else self.revenue_metric
        if skill_code not in {
            "revenue_decline_diagnosis",
            "gross_profit_change_decomposition",
        }:
            return ()
        result = DiagnosticService(self.db, self.user).decompose(
            metric, start, end_exclusive, comparison, limit=10
        )
        return tuple({
            "driver": row["driver"],
            "contribution": row["contribution"],
            "classification": "verified_calculation",
        } for row in result["bridge"])

    def metric_metadata(self, metric_id: str) -> dict:
        # The charging metric contract also carries its deterministic formula.
        # Metadata consumers need only the first two fields.
        name, unit, *_ = METRICS[metric_id]
        return {
            "metric_id": metric_id,
            "metric_name": name,
            "unit": unit,
            "metric_version": "0.1.0",
            "source": "published charging_ops semantic layer",
        }

    def report_metrics(self) -> tuple[str, ...]:
        return (
            "charging_revenue",
            "order_count",
            "gross_profit",
            "station_utilization_rate",
            "device_online_rate",
        )


@dataclass
class SalesOpsAnalysisAdapter:
    db: Session
    user: User
    scenario_id: str = "sales_ops"
    revenue_metric: str = "sales_revenue"
    order_metric: str = "order_count"
    gross_profit_metric: str = "gross_profit"
    efficiency_metric: str | None = None
    default_dimension: str = "region"

    def metrics(self, start: date, end_exclusive: date, metric_ids: tuple[str, ...]) -> dict:
        values = SalesOpsMetricService(self.db).calculate(start, end_exclusive)
        return {metric_id: values[metric_id] for metric_id in metric_ids}

    def breakdown(
        self,
        start: date,
        end_exclusive: date,
        metric_id: str,
        dimension: str,
        limit: int,
    ) -> tuple[dict, ...]:
        if metric_id not in {"sales_revenue", "order_count", "gross_profit"}:
            raise ValueError("sales_ops metric does not support contribution breakdown")
        rows = SalesOpsMetricService(self.db).by_dimension(
            start, end_exclusive, dimension=dimension, limit=limit
        )
        return tuple({
            "dimension": row[dimension],
            "dimension_name": row[dimension],
            "value": row[metric_id],
        } for row in rows)

    def drivers(
        self,
        skill_code: str,
        start: date,
        end_exclusive: date,
        comparison: str,
    ) -> tuple[dict, ...]:
        if skill_code not in {
            "revenue_decline_diagnosis",
            "gross_profit_change_decomposition",
        }:
            return ()
        previous_start, previous_end = previous_period(start, end_exclusive, comparison)
        current = SalesOpsMetricService(self.db).calculate(start, end_exclusive)
        previous = SalesOpsMetricService(self.db).calculate(previous_start, previous_end)
        if skill_code == "revenue_decline_diagnosis":
            current_quantity = current["sales_quantity"] or 0
            previous_quantity = previous["sales_quantity"] or 0
            previous_price = (previous["sales_revenue"] or 0) / previous_quantity if previous_quantity else 0
            current_price = (current["sales_revenue"] or 0) / current_quantity if current_quantity else 0
            quantity_effect = (current_quantity - previous_quantity) * previous_price
            price_effect = current_quantity * (current_price - previous_price)
            residual = (current["sales_revenue"] or 0) - (previous["sales_revenue"] or 0) - quantity_effect - price_effect
            return (
                {"driver": "sales_quantity_effect", "contribution": round(quantity_effect, 6), "classification": "verified_calculation"},
                {"driver": "average_price_effect", "contribution": round(price_effect, 6), "classification": "verified_calculation"},
                {"driver": "rounding_residual", "contribution": round(residual, 6), "classification": "verified_calculation"},
            )
        return (
            {
                "driver": "sales_revenue_change",
                "contribution": round((current["sales_revenue"] or 0) - (previous["sales_revenue"] or 0), 6),
                "classification": "verified_calculation",
            },
            {
                "driver": "implied_cost_change",
                "contribution": round(
                    -(
                        ((current["sales_revenue"] or 0) - (current["gross_profit"] or 0))
                        - ((previous["sales_revenue"] or 0) - (previous["gross_profit"] or 0))
                    ),
                    6,
                ),
                "classification": "verified_calculation",
            },
        )

    def metric_metadata(self, metric_id: str) -> dict:
        name, unit = SALES_METRICS[metric_id]
        return {
            "metric_id": metric_id,
            "metric_name": name,
            "unit": unit,
            "metric_version": "1.0.0",
            "source": "published sales_ops semantic layer",
        }

    def report_metrics(self) -> tuple[str, ...]:
        return ("sales_revenue", "order_count", "gross_profit", "gross_margin", "refund_rate")


class AnalysisAdapterRegistry:
    def __init__(self, db: Session, user: User) -> None:
        self._adapters: dict[str, AnalysisAdapter] = {
            "charging_ops": ChargingOpsAnalysisAdapter(db, user),
            "sales_ops": SalesOpsAnalysisAdapter(db, user),
        }

    def get(self, scenario_id: str) -> AnalysisAdapter:
        adapter = self._adapters.get(scenario_id)
        if adapter is None:
            raise ValueError("analysis scenario is not registered")
        return adapter
