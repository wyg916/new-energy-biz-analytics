import json
from pathlib import Path

import pytest


pytestmark = pytest.mark.no_db


def test_memory_lifecycle_fixed_evaluation_manifest_is_complete():
    path = Path(__file__).parent / "evaluation" / "memory_lifecycle_41.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload["cases"]
    assert payload["data_classification"] == "simulated"
    assert [case["id"] for case in cases] == [f"ML-{index:02d}" for index in range(1, 13)]
    assert {case["category"] for case in cases} == {
        "ttl", "decay", "cold", "usage_signal", "conflict", "forget",
        "legal_hold", "outbox", "retry", "cross_store",
        "delete_verification", "authorization",
    }
