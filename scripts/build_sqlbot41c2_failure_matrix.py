"""Build the required seven-case 4.1C2 failure closure matrix."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    before = json.loads(args.before.read_text(encoding="utf-8"))
    after = json.loads(args.after.read_text(encoding="utf-8"))
    failed_before = [
        item for item in before["results"] if item.get("final_status") != "PASS"
    ]
    if len(failed_before) != 7:
        raise RuntimeError("4.1C source evidence must contain exactly seven failures")
    after_by_id = {item["case_id"]: item for item in after["results"]}
    results = []
    for original in failed_before:
        current = after_by_id.get(original["case_id"])
        if current is None:
            raise RuntimeError("4.1C2 evidence is missing a prior failed case")
        generation = current.get("generation_attempts") or ()
        guard_reason = next(
            (item.get("error") for item in reversed(generation) if item.get("error")),
            current.get("error"),
        )
        results.append({
            "case_id": current["case_id"],
            "question": current["question"],
            "expected_behavior": current["expected_decision"],
            "query_understanding": current.get("query_understanding"),
            "retrieved_schema": current.get("schema_retrieval_result"),
            "prompt_version": current.get("prompt_version"),
            "model_raw_output": current.get("model_raw_return"),
            "generated_sql": current.get("generated_sql"),
            "repair_input": current.get("repair_input"),
            "repair_output": current.get("repair_output"),
            "guard_reason": guard_reason,
            "semantic_reason": {
                "final_error": current.get("error"),
                "time_range_alignment": current.get("time_range_alignment"),
                "dimension_alignment": current.get("dimension_alignment"),
                "sort_alignment": current.get("sort_alignment"),
                "hallucinated_tables": current.get("hallucinated_tables") or [],
                "hallucinated_fields": current.get("hallucinated_fields") or [],
            },
            "latency": {
                "before_ms": original.get("latency_ms"),
                "after_ms": current.get("latency_ms"),
                "after_profile": current.get("latency_profile"),
            },
            "before_status": original.get("final_status"),
            "before_error": original.get("error"),
            "final_status": current.get("final_status"),
        })
    report = {
        "evidence_type": "sqlbot41c2_real_smoke_20_failure_matrix",
        "generated_at": datetime.now(UTC).isoformat(),
        "before_source": args.before.name,
        "after_source": args.after.name,
        "total": len(results),
        "closed": sum(item["final_status"] == "PASS" for item in results),
        "open": sum(item["final_status"] != "PASS" for item in results),
        "results": results,
        "secret_values_exposed": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": "PASS" if report["open"] == 0 else "PARTIAL",
        "closed": report["closed"],
        "open": report["open"],
    }))


if __name__ == "__main__":
    main()
