from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


class SkillRequest(BaseModel):
    skill_code: str
    scenario_id: str
    start: date
    end_exclusive: date
    comparison: Literal["mom", "yoy"] = "mom"
    metric_id: str | None = None
    dimension: str | None = None
    session_id: str | None = None
    run_id: str | None = None
    trace_id: str | None = None
    limit: int = Field(default=10, ge=1, le=50)


class SkillOutput(BaseModel):
    conclusion: str
    metric_change: dict[str, Any]
    time_comparison: dict[str, Any]
    contribution_breakdown: list[dict[str, Any]]
    anomalies: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    candidate_causes: list[dict[str, Any]]
    recommended_actions: list[dict[str, Any]]
    limitations: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    run_id: str
    trace_id: str
    task_id: str
    skill_code: str
    scenario_id: str
    steps: list[dict[str, Any]]
    data_classification: Literal["simulated"] = "simulated"
