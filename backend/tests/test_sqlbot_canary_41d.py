from collections import Counter, defaultdict

import pytest

from scripts.run_sqlbot_canary_acceptance import (
    _bucket,
    _cohort,
    _conversation_id,
)
from scripts.verify_sqlbot41d_startup_readiness import (
    _configuration,
    _router_ready,
)


pytestmark = pytest.mark.no_db


@pytest.mark.parametrize(
    ("stage", "expected_total", "expected_selected"),
    (("canary-5", 100, 5), ("canary-20", 200, 40)),
)
def test_canary_acceptance_cohort_reuses_scoped_identities(
    stage: str,
    expected_total: int,
    expected_selected: int,
) -> None:
    cohort = _cohort(stage)
    assert len(cohort) == expected_total
    assert sum(item["selected"] for item in cohort) == expected_selected

    subjects: dict[tuple[str, bool], set[str]] = defaultdict(set)
    percentage = {"canary-5": 5.0, "canary-20": 20.0}[stage]
    for item in cohort:
        subjects[(item["scenario"], item["selected"])].add(item["subject"])
        assert (_bucket(item["subject"], item["scenario"]) < percentage) is item[
            "selected"
        ]
    assert all(len(values) == 1 for values in subjects.values())
    assert Counter(item["scenario"] for item in cohort) == {
        "charging_ops": expected_total // 2,
        "sales_ops": expected_total // 2,
    }


def test_selected_requests_share_a_follow_up_conversation_per_scenario() -> None:
    selected = [item for item in _cohort("canary-20") if item["selected"]]
    conversations = {
        scenario: {
            _conversation_id("canary-20", "run", item, index)
            for index, item in enumerate(selected)
            if item["scenario"] == scenario
        }
        for scenario in ("charging_ops", "sales_ops")
    }
    assert conversations == {
        "charging_ops": {"s41d-canary-20-run-charging_ops-canary"},
        "sales_ops": {"s41d-canary-20-run-sales_ops-canary"},
    }


def test_control_requests_keep_isolated_conversations() -> None:
    controls = [item for item in _cohort("canary-20") if not item["selected"]]
    conversations = {
        _conversation_id("canary-20", "run", item, index)
        for index, item in enumerate(controls)
    }
    assert len(conversations) == len(controls)


@pytest.mark.parametrize(
    ("mode", "engine_mode", "percentage"),
    (
        ("SHADOW", "SHADOW", 0.0),
        ("CANARY_5", "CANARY", 5.0),
        ("CANARY_20", "CANARY", 20.0),
        ("SCOPED_STABLE", "SCOPED_STABLE", 100.0),
    ),
)
def test_startup_readiness_exposes_safe_controlled_configuration(
    mode: str,
    engine_mode: str,
    percentage: float,
) -> None:
    configuration = _configuration(mode)

    assert configuration["query_engine_mode"] == engine_mode
    assert configuration["canary_percentage"] == percentage
    assert configuration["default_is_global_stable"] is False
    assert _router_ready(mode) is True
