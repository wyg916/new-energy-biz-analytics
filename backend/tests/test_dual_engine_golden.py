import json
import os
from copy import deepcopy
from pathlib import Path

import pytest

from app.evaluation.dual_engine_golden import evaluate_golden_contract

pytestmark = pytest.mark.no_db


def _source_path() -> Path:
    override = os.environ.get("DUAL_ENGINE_GOLDEN_PATH")
    if override:
        return Path(override)
    return (
        Path(__file__).resolve().parents[2]
        / "tests"
        / "evaluation"
        / "nl2sql_dual_engine_v1.json"
    )


def _load_source() -> dict:
    return json.loads(_source_path().read_text(encoding="utf-8"))


def test_dual_engine_golden_contract_is_complete_and_safe():
    report = evaluate_golden_contract(_load_source())

    assert report["contract_status"] == "PASS"
    assert report["total"] == report["passed"] == 100
    assert report["failed"] == 0
    assert set(report["category_counts"].values()) == {20}
    assert set(report["scenario_counts"]) == {
        "charging_ops",
        "sales_ops",
    }
    assert report["security_candidates"] == 10
    assert report["dangerous_sql_successes"] == 0
    assert report["permission_attack_successes"] == 0
    assert report["runtime_evaluation"]["status"] == (
        "SQLBOT_RUNTIME_PENDING"
    )
    assert report["runtime_evaluation"]["execution_accuracy"] is None
    assert report["canary_eligible"] is False


def test_contract_detects_a_dangerous_sql_that_passes_the_guard():
    source = deepcopy(_load_source())
    case = next(
        item for item in source["cases"] if item["case_id"] == "AR-011"
    )
    case["candidate_sql"] = "SELECT order_id FROM sales_order LIMIT 10"

    report = evaluate_golden_contract(source)

    assert report["contract_status"] == "FAIL"
    assert report["dangerous_sql_successes"] == 1
    assert "AR-011" in report["failed_ids"]


def test_contract_rejects_unknown_scenario_metric():
    source = deepcopy(_load_source())
    source["cases"][0]["expected_metrics"] = ["invented_metric"]

    report = evaluate_golden_contract(source)

    assert report["contract_status"] == "FAIL"
    assert source["cases"][0]["case_id"] in report["failed_ids"]

