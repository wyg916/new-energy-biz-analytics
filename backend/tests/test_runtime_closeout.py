import json
from pathlib import Path

import pytest

from app.evaluation.runtime_closeout import (
    ModelContractPresence,
    build_blocked_runtime_report,
    runtime_smoke_cases,
)


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.no_db


def test_runtime_smoke_cases_cover_both_scenarios_and_active_dates() -> None:
    cases = runtime_smoke_cases(
        charging_min_date="2025-01-01",
        charging_max_date="2026-06-30",
        sales_min_date="2025-01-01",
        sales_max_date="2026-06-30",
    )

    assert len(cases) == 10
    assert [case["scenario"] for case in cases].count("charging_ops") == 5
    assert [case["scenario"] for case in cases].count("sales_ops") == 5
    assert all("2026-06-30" in case["question"] for case in cases)


def test_missing_model_contract_records_not_executed_runtime_evidence() -> None:
    source = json.loads(
        (
            ROOT / "tests" / "evaluation" / "nl2sql_dual_engine_v1.json"
        ).read_text(encoding="utf-8")
    )

    report = build_blocked_runtime_report(
        source,
        model_contract=ModelContractPresence(
            provider=False,
            base_url=False,
            model_name=False,
            credential_ref=True,
        ),
        charging_min_date="2025-01-01",
        charging_max_date="2026-06-30",
        sales_min_date="2025-01-01",
        sales_max_date="2026-06-30",
    )

    assert report["runtime_status"] == "HUMAN_MODEL_CONFIG_REQUIRED"
    assert report["model_called"] is False
    assert report["mock_provider_used"] is False
    assert report["external_request_count"] == 0
    assert report["smoke"]["executed"] == 0
    assert report["smoke"]["not_executed"] == 10
    assert report["golden"]["executed"] == 0
    assert report["golden"]["not_executed"] == 100
    assert all(
        value is None for value in report["golden"]["metrics"].values()
    )
    assert report["canary"]["eligible"] is False


def test_complete_contract_still_requires_real_live_execution() -> None:
    source = {"name": "test", "version": "1", "cases": [
        {"case_id": f"case-{index}", "scenario_id": "charging_ops"}
        for index in range(100)
    ]}

    report = build_blocked_runtime_report(
        source,
        model_contract=ModelContractPresence(
            provider=True,
            base_url=True,
            model_name=True,
            credential_ref=True,
        ),
        charging_min_date="2025-01-01",
        charging_max_date="2026-06-30",
        sales_min_date="2025-01-01",
        sales_max_date="2026-06-30",
    )

    assert report["runtime_status"] == "LIVE_EXECUTION_REQUIRED"
    assert report["model_called"] is False
    assert report["golden"]["status"] == "NOT_EXECUTED"
