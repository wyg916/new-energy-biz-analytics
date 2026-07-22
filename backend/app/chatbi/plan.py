from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.services.metric_catalog import ALLOWED_DIMENSIONS, METRICS


class TimeRange(BaseModel):
    start: date
    end_exclusive: date
    grain: Literal["day", "week", "month", "quarter", "year"] | None = None


class Filter(BaseModel):
    field: Literal["region", "city", "station", "station_type", "operator", "user_segment", "expense_type"]
    operator: Literal["eq", "in"] = "eq"
    value: str | list[str]


class Clarification(BaseModel):
    reason_code: Literal["missing_metric", "ambiguous_metric", "missing_time", "ambiguous_scope", "unsupported_request", "out_of_data_range"]
    question: str


class QueryPlan(BaseModel):
    version: Literal["0.1.0"] = "0.1.0"
    status: Literal["ready", "needs_clarification", "rejected"]
    intent: Literal["metric_lookup", "trend", "comparison", "ranking", "diagnosis", "diagnose_revenue_change", "diagnose_gross_profit_change", "anomaly_lookup", "metric_definition", "unsupported"]
    metrics: list[str] = Field(default_factory=list, max_length=5)
    time_range: TimeRange | None = None
    filters: list[Filter] = Field(default_factory=list, max_length=10)
    dimensions: list[str] = Field(default_factory=list, max_length=3)
    analysis: list[str] = Field(default_factory=list)
    comparison: dict | None = None
    context_resolution: dict | None = None
    sort: list[dict] = Field(default_factory=list)
    limit: int = Field(default=100, ge=1, le=5000)
    clarification: Clarification | None = None

    @model_validator(mode="after")
    def semantic_validation(self) -> "QueryPlan":
        if set(self.metrics) - METRICS.keys():
            raise ValueError("unknown metric")
        if set(self.dimensions) - set(ALLOWED_DIMENSIONS):
            raise ValueError("unknown dimension")
        if self.status == "ready" and (not self.metrics or self.time_range is None or self.clarification is not None):
            raise ValueError("ready plan requires metric/time and no clarification")
        if self.status == "needs_clarification" and self.clarification is None:
            raise ValueError("clarification is required")
        if self.time_range and not self.time_range.start < self.time_range.end_exclusive:
            raise ValueError("invalid time range")
        return self


QUERY_PLAN_JSON_SCHEMA = QueryPlan.model_json_schema()
