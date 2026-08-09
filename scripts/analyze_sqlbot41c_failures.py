"""Classify the preserved 4.1B real-model Smoke failures without inventing data."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import sqlglot
from sqlglot import exp


SCHEMAS = {
    "charging_ops": "semantic_sqlbot_charging",
    "sales_ops": "semantic_sqlbot_sales",
}


def _classification(item: dict) -> tuple[str, str | None]:
    error = str(item.get("error") or "")
    if not item.get("generated_sql"):
        if "TIMEOUT" in error:
            return "NO_SQL_GENERATED", "MODEL_TIMEOUT"
        if "UPSTREAM_UNAVAILABLE" in error:
            return "NO_SQL_GENERATED", "UPSTREAM_UNAVAILABLE"
        return "NO_SQL_GENERATED", error or "UNKNOWN"
    if "explicit schema" in error or "cross-database" in error:
        return "SCHEMA_PREFIX", None
    labels = (
        ("UNKNOWN_TABLE", "relation"),
        ("UNKNOWN_COLUMN", "field"),
        ("INVALID_JOIN", "join"),
        ("PII", "PII"),
        ("MISSING_LIMIT", "LIMIT"),
        ("CTE", "CTE"),
    )
    for label, marker in labels:
        if marker.lower() in error.lower():
            return label, None
    return "OTHER", error or None


def _parse_and_normalize(sql: str | None, scenario: str) -> dict:
    if not sql:
        return {"parser_result": "NOT_EXECUTED", "normalized_sql": None}
    try:
        root = sqlglot.parse_one(sql, read="postgres")
    except sqlglot.errors.ParseError as exc:
        return {
            "parser_result": "REJECTED",
            "parser_error": type(exc).__name__,
            "normalized_sql": None,
        }
    approved = SCHEMAS.get(scenario)
    for table in root.find_all(exp.Table):
        if table.db == approved and not table.catalog:
            table.set("db", None)
    return {
        "parser_result": "PASSED",
        "statement_type": type(root).__name__,
        "normalized_sql": root.sql(dialect="postgres"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.input.read_text(encoding="utf-8-sig"))
    results = []
    counts: Counter[str] = Counter()
    for item in source["results"]:
        category, detail = _classification(item)
        counts[category] += 1
        parsed = _parse_and_normalize(item.get("generated_sql"), item["scenario"])
        results.append({
            "case_id": item["case_id"],
            "scenario": item["scenario"],
            "original_user_question": item["question"],
            "schema_retrieval_result": "NOT_CAPTURED_IN_41B_EVIDENCE",
            "final_schema_context": "NOT_CAPTURED_IN_41B_EVIDENCE",
            "prompt_version": "sqlbot-schema-4.1/41b",
            "model_raw_return": "NOT_PERSISTED_BY_DESIGN",
            "sql_generated": item.get("generated_sql") is not None,
            "sql_original": item.get("generated_sql"),
            **parsed,
            "schema_validation": "NOT_SEPARATELY_CAPTURED_IN_41B_EVIDENCE",
            "join_validation": "NOT_SEPARATELY_CAPTURED_IN_41B_EVIDENCE",
            "permission_pii_validation": "NO_VIOLATION_OBSERVED",
            "query_guard": item["guard_result"],
            "final_rejection_reason": item.get("error"),
            "failure_category": category,
            "failure_detail": detail,
            "latency_ms": item["latency_ms"],
        })
    report = {
        "evidence_type": "sqlbot41c_real_smoke_failure_analysis",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_evidence": args.input.name,
        "source_total": source["total"],
        "classification_counts": dict(sorted(counts.items())),
        "evidence_gaps": [
            "4.1B did not persist retrieved Schema Context or sanitized raw model envelope",
            "4.1C runtime evidence must capture those fields prospectively",
        ],
        "security_contract_changed": False,
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "PASS", "counts": report["classification_counts"]}))


if __name__ == "__main__":
    main()
