from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Any

from app.chatbi.guard import QueryRejected, guard_sqlbot_sql
from app.platform.query_engine import QueryContext
from app.scenarios.charging_ops.manifest import (
    ALLOWED_DIMENSIONS as CHARGING_DIMENSIONS,
)
from app.scenarios.charging_ops.manifest import METRICS as CHARGING_METRICS
from app.scenarios.sales_ops.metrics import SALES_METRICS

EXPECTED_CATEGORIES = {
    "single_metric",
    "filter_sort",
    "trend_comparison",
    "multi_table_dimension",
    "ambiguity_security_refusal",
}
EXPECTED_CATEGORY_COUNT = 20
EXPECTED_TOTAL = 100
ALLOWED_DECISIONS = {"QUERY", "CLARIFY", "REJECT"}
ALLOWED_TARGET_ENGINES = {
    "deterministic",
    "sqlbot_long_tail",
    "query_guard",
    "none",
}
SCENARIO_METRICS = {
    "charging_ops": frozenset(CHARGING_METRICS),
    "sales_ops": frozenset(SALES_METRICS),
}
SCENARIO_DIMENSIONS = {
    "charging_ops": frozenset(CHARGING_DIMENSIONS),
    "sales_ops": frozenset(
        {
            "date",
            "region",
            "channel",
            "product",
            "category",
            "customer_segment",
            "salesperson",
            "organization",
        }
    ),
}
PERMISSION_ATTACK_CASE_IDS = frozenset({"AR-018", "AR-019"})
RUNTIME_METRIC_NAMES = (
    "sql_execution_success_rate",
    "execution_accuracy",
    "metric_value_accuracy",
    "time_range_accuracy",
    "dimension_accuracy",
    "permission_violation_rate",
    "hallucinated_table_rate",
    "hallucinated_field_rate",
    "refusal_accuracy",
    "p50_ms",
    "p95_ms",
    "token_usage",
    "shadow_consistency",
)


def _query_context(scenario_id: str) -> QueryContext:
    if scenario_id == "charging_ops":
        allowed_relations = {
            "fact_charging_session": (
                "session_id",
                "charging_revenue",
                "station_id",
                "region_id",
            ),
        }
    else:
        allowed_relations = {
            "sales_order": (
                "order_id",
                "net_revenue",
                "gross_profit",
                "region_id",
            ),
            "sales_customer": (
                "customer_id",
                "customer_segment",
            ),
        }
    return QueryContext(
        conversation_id=f"golden-{scenario_id}",
        scenario_version="golden-contract",
        semantic_version="golden-contract",
        semantic_model_version_id=f"golden-semantic-{scenario_id}",
        dataset_version="golden-contract",
        dataset_version_id=f"golden-dataset-{scenario_id}",
        datasource_id=None,
        allowed_relations=allowed_relations,
        execution_mode="offline_guard_validation",
        max_rows=500,
    )


def evaluate_golden_contract(source: dict[str, Any]) -> dict[str, Any]:
    """Validate the fixed set without claiming unavailable SQLBot runtime results."""
    cases = source.get("cases")
    global_errors: list[str] = []
    if source.get("data_classification") != "simulated":
        global_errors.append("data_classification must be simulated")
    if source.get("runtime_status") != "SQLBOT_RUNTIME_PENDING":
        global_errors.append(
            "offline P1B contract must declare SQLBOT_RUNTIME_PENDING"
        )
    period = source.get("data_period")
    if not isinstance(period, dict) or {
        "start",
        "end_exclusive",
        "timezone",
    } - set(period):
        global_errors.append("data_period contract is incomplete")
    if not isinstance(cases, list):
        cases = []
        global_errors.append("cases must be a list")
    if len(cases) != EXPECTED_TOTAL:
        global_errors.append(
            f"expected {EXPECTED_TOTAL} cases, found {len(cases)}"
        )

    category_counts = Counter(
        case.get("category") for case in cases if isinstance(case, dict)
    )
    expected_counts = {
        category: EXPECTED_CATEGORY_COUNT
        for category in sorted(EXPECTED_CATEGORIES)
    }
    if dict(sorted(category_counts.items())) != expected_counts:
        global_errors.append(
            f"category counts must be {expected_counts}, found "
            f"{dict(sorted(category_counts.items()))}"
        )

    case_ids = [
        case.get("case_id") for case in cases if isinstance(case, dict)
    ]
    questions = [
        case.get("question") for case in cases if isinstance(case, dict)
    ]
    if len(case_ids) != len(set(case_ids)):
        global_errors.append("case_id values must be unique")
    if len(questions) != len(set(questions)):
        global_errors.append("question values must be unique")

    scenario_counts = Counter()
    target_engine_counts = Counter()
    decision_counts = Counter()
    category_scenarios: dict[str, set[str]] = {
        category: set() for category in EXPECTED_CATEGORIES
    }
    results: list[dict[str, Any]] = []
    dangerous_sql_successes = 0
    permission_attack_successes = 0
    security_candidates = 0

    for position, original_case in enumerate(cases, start=1):
        errors: list[str] = []
        if not isinstance(original_case, dict):
            results.append(
                {
                    "case_id": f"invalid-position-{position}",
                    "passed": False,
                    "errors": ["case must be an object"],
                }
            )
            continue
        case = deepcopy(original_case)
        case_id = case.get("case_id")
        category = case.get("category")
        scenario_id = case.get("scenario_id")
        decision = case.get("expected_decision")
        target_engine = case.get("target_engine")
        question = case.get("question")

        if not isinstance(case_id, str) or not case_id:
            errors.append("case_id must be a non-empty string")
        if category not in EXPECTED_CATEGORIES:
            errors.append("category is not allowlisted")
        if scenario_id not in SCENARIO_METRICS:
            errors.append("scenario_id is not allowlisted")
        else:
            scenario_counts[scenario_id] += 1
            if category in category_scenarios:
                category_scenarios[category].add(scenario_id)
        if not isinstance(question, str) or not question.strip():
            errors.append("question must be a non-empty string")
        if decision not in ALLOWED_DECISIONS:
            errors.append("expected_decision is invalid")
        else:
            decision_counts[decision] += 1
        if target_engine not in ALLOWED_TARGET_ENGINES:
            errors.append("target_engine is invalid")
        else:
            target_engine_counts[target_engine] += 1
        if decision == "QUERY" and target_engine not in {
            "deterministic",
            "sqlbot_long_tail",
        }:
            errors.append("QUERY cases must target a query engine")
        if decision in {"CLARIFY", "REJECT"} and target_engine in {
            "deterministic",
            "sqlbot_long_tail",
        }:
            errors.append(
                "non-query cases must not target an executable query engine"
            )
        if category != "ambiguity_security_refusal" and decision != "QUERY":
            errors.append("ordinary analytical categories must expect QUERY")
        if category == "ambiguity_security_refusal" and decision == "QUERY":
            errors.append(
                "ambiguity/security/refusal category must not expect QUERY"
            )

        metrics = case.get("expected_metrics")
        dimensions = case.get("expected_dimensions")
        if not isinstance(metrics, list) or not all(
            isinstance(item, str) for item in metrics
        ):
            errors.append("expected_metrics must be a string list")
            metrics = []
        if not isinstance(dimensions, list) or not all(
            isinstance(item, str) for item in dimensions
        ):
            errors.append("expected_dimensions must be a string list")
            dimensions = []
        if scenario_id in SCENARIO_METRICS:
            unknown_metrics = set(metrics) - SCENARIO_METRICS[scenario_id]
            if unknown_metrics:
                errors.append(
                    f"unknown scenario metrics: {sorted(unknown_metrics)}"
                )
            unknown_dimensions = (
                set(dimensions) - SCENARIO_DIMENSIONS[scenario_id]
            )
            if unknown_dimensions:
                errors.append(
                    f"unknown scenario dimensions: "
                    f"{sorted(unknown_dimensions)}"
                )

        expected_metric = case.get("expected_metric")
        if expected_metric is not None and expected_metric not in metrics:
            errors.append("expected_metric must be null or one of expected_metrics")
        expected_time_range = case.get("expected_time_range")
        if not isinstance(expected_time_range, dict) or expected_time_range.get("mode") not in {
            "explicit", "semantic_default", "out_of_dataset_range"
        }:
            errors.append("expected_time_range oracle is invalid")
        elif expected_time_range.get("mode") == "explicit" and not {
            "start", "end_exclusive"
        }.issubset(expected_time_range):
            errors.append("explicit expected_time_range is incomplete")
        expected_sort = case.get("expected_sort")
        if expected_sort is not None and (
            not isinstance(expected_sort, dict)
            or expected_sort.get("direction") not in {"ASC", "DESC"}
            or not isinstance(expected_sort.get("limit"), int)
            or not 1 <= expected_sort["limit"] <= 500
        ):
            errors.append("expected_sort oracle is invalid")
        row_range = case.get("expected_row_count_range")
        if not isinstance(row_range, dict) or not all(
            isinstance(row_range.get(key), int) for key in ("min", "max")
        ) or not 0 <= row_range["min"] <= row_range["max"] <= 500:
            errors.append("expected_row_count_range oracle is invalid")
        result_hash = case.get("expected_result_hash")
        tolerance = case.get("expected_result_tolerance")
        if decision == "QUERY" and not (
            isinstance(result_hash, str)
            or (
                isinstance(tolerance, dict)
                and isinstance(tolerance.get("relative"), (int, float))
                and isinstance(tolerance.get("absolute"), (int, float))
            )
        ):
            errors.append("query oracle requires expected_result_hash or tolerance")
        if case.get("expected_rejection") is not (decision == "REJECT"):
            errors.append("expected_rejection does not match expected_decision")
        allowed_variants = case.get("allowed_sql_variants")
        if not isinstance(allowed_variants, list) or not allowed_variants or not all(
            isinstance(item, str) and item for item in allowed_variants
        ):
            errors.append("allowed_sql_variants oracle is invalid")

        candidate_sql = case.get("candidate_sql")
        if target_engine == "query_guard":
            security_candidates += 1
            if decision != "REJECT":
                errors.append("query_guard cases must expect REJECT")
            if not isinstance(candidate_sql, str) or not candidate_sql:
                errors.append("query_guard case must include candidate_sql")
            elif scenario_id in SCENARIO_METRICS:
                try:
                    guard_sqlbot_sql(
                        candidate_sql,
                        _query_context(scenario_id),
                    )
                except QueryRejected:
                    pass
                except Exception as exc:  # pragma: no cover - defensive evidence
                    errors.append(
                        f"query guard evaluation failed: "
                        f"{type(exc).__name__}"
                    )
                else:
                    dangerous_sql_successes += 1
                    if case_id in PERMISSION_ATTACK_CASE_IDS:
                        permission_attack_successes += 1
                    errors.append("dangerous candidate SQL passed Query Guard")
        elif candidate_sql is not None:
            errors.append("candidate_sql is only valid for query_guard cases")

        results.append(
            {
                "case_id": case_id,
                "passed": not errors,
                "errors": errors,
            }
        )

    for category, scenarios in sorted(category_scenarios.items()):
        if scenarios != set(SCENARIO_METRICS):
            global_errors.append(
                f"{category} must cover both scenarios, found "
                f"{sorted(scenarios)}"
            )

    failed_ids = [
        result["case_id"] for result in results if not result["passed"]
    ]
    runtime_evaluation = {
        "status": "SQLBOT_RUNTIME_PENDING",
        **{metric: None for metric in RUNTIME_METRIC_NAMES},
    }
    contract_passed = not global_errors and not failed_ids
    return {
        "evaluation_set": source.get("name"),
        "evaluation_version": source.get("version"),
        "data_classification": source.get("data_classification"),
        "contract_status": "PASS" if contract_passed else "FAIL",
        "contract_scope": (
            "offline structure, semantic references, refusal labels, and "
            "Query Guard negative candidates"
        ),
        "total": len(cases),
        "passed": len(results) - len(failed_ids),
        "failed": len(failed_ids),
        "failed_ids": failed_ids,
        "global_errors": global_errors,
        "category_counts": dict(sorted(category_counts.items())),
        "scenario_counts": dict(sorted(scenario_counts.items())),
        "target_engine_counts": dict(sorted(target_engine_counts.items())),
        "decision_counts": dict(sorted(decision_counts.items())),
        "security_candidates": security_candidates,
        "dangerous_sql_successes": dangerous_sql_successes,
        "permission_attack_candidates": len(PERMISSION_ATTACK_CASE_IDS),
        "permission_attack_successes": permission_attack_successes,
        "runtime_evaluation": runtime_evaluation,
        "canary_eligible": False,
        "canary_blockers": [
            "SQLBOT_RUNTIME_PENDING",
            "runtime execution metrics are unavailable",
        ],
        "results": results,
    }
