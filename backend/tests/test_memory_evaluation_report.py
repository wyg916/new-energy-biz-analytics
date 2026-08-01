import pytest

from app.memory.evaluation import (
    REQUIRED_DISTRIBUTION,
    EvaluationObservation,
    evaluate_observations,
)


pytestmark = pytest.mark.no_db


def test_memory_skill_evaluator_enforces_exact_40_plus_40_distribution_and_safety():
    observations = []
    for track, categories in REQUIRED_DISTRIBUTION.items():
        for category, count in categories.items():
            observations.extend(
                EvaluationObservation(
                    case_id=f"{track}-{category}-{index}",
                    track=track,
                    category=category,
                    passed=True,
                    latency_ms=index,
                    storage_bytes_delta=10 if track == "memory" else 0,
                )
                for index in range(count)
            )
    report = evaluate_observations(observations)
    assert report["status"] == "PASS"
    assert report["total"] == report["passed"] == 80
    assert sum(report["distribution"]["memory"].values()) == 40
    assert sum(report["distribution"]["skill"].values()) == 40
    assert not any(report["safety"].values())
    assert report["metrics"]["storage_growth_bytes"] == 400
