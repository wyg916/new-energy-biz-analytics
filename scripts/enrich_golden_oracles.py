"""Add deterministic, machine-verifiable oracle fields to the fixed 100 cases."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def time_range(question: str) -> dict[str, str]:
    if "2025年和2026年上半年" in question:
        return {"mode": "explicit", "start": "2025-01-01", "end_exclusive": "2026-07-01"}
    if "最近12个月" in question and "2026年6月" in question:
        return {"mode": "explicit", "start": "2025-07-01", "end_exclusive": "2026-07-01"}
    if "2026年第一和第二季度" in question or "2026年上半年" in question:
        return {"mode": "explicit", "start": "2026-01-01", "end_exclusive": "2026-07-01"}
    if "2026年第二季度" in question:
        return {"mode": "explicit", "start": "2026-04-01", "end_exclusive": "2026-07-01"}
    if "2026年6月" in question:
        return {"mode": "explicit", "start": "2026-06-01", "end_exclusive": "2026-07-01"}
    if "2026年各月" in question or "2026年每月" in question:
        return {"mode": "explicit", "start": "2026-01-01", "end_exclusive": "2027-01-01"}
    if "明年" in question:
        return {"mode": "out_of_dataset_range"}
    return {"mode": "semantic_default"}


def sort_oracle(question: str) -> dict[str, int | str] | None:
    descending = ("最高", "倒序", "降序", "排名", "前")
    ascending = ("最低", "最少", "升序")
    direction = "ASC" if any(word in question for word in ascending) else (
        "DESC" if any(word in question for word in descending) else None
    )
    if direction is None:
        return None
    match = re.search(r"(?:前)?(\d+)(?:个|名)", question)
    return {"direction": direction, "limit": int(match.group(1)) if match else 500}


def enrich(case: dict) -> None:
    decision = str(case["expected_decision"])
    query = decision == "QUERY"
    metrics = list(case.get("expected_metrics") or [])
    case["expected_metric"] = metrics[0] if metrics else None
    case["expected_time_range"] = time_range(str(case["question"]))
    case["expected_sort"] = sort_oracle(str(case["question"]))
    case["expected_row_count_range"] = {
        "min": 0,
        "max": 1 if query and case["category"] == "single_metric" else (500 if query else 0),
    }
    case["expected_result_hash"] = None
    case["expected_result_tolerance"] = (
        {"relative": 0.0001, "absolute": 0.01} if query else None
    )
    case["expected_rejection"] = decision == "REJECT"
    case["allowed_sql_variants"] = (
        ["semantic_equivalent_postgres_select", "parameterized_or_literal_date_bounds"]
        if query
        else ["no_sql_execution"]
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    source = json.loads(args.path.read_text(encoding="utf-8"))
    cases = source.get("cases")
    if not isinstance(cases, list) or len(cases) != 100:
        raise RuntimeError("Golden source must contain exactly 100 cases")
    source["oracle_version"] = "p2b-1.0"
    for case in cases:
        enrich(case)
    args.path.write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
