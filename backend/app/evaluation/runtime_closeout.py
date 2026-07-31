from __future__ import annotations

from dataclasses import dataclass
from typing import Any


RUNTIME_METRIC_NAMES = (
    "model_call_success_rate",
    "sql_generation_rate",
    "sql_guard_pass_rate",
    "sql_execution_rate",
    "execution_accuracy",
    "metric_value_accuracy",
    "time_range_accuracy",
    "dimension_accuracy",
    "sort_accuracy",
    "permission_violation_rate",
    "cross_scenario_violation_rate",
    "hallucinated_table_rate",
    "hallucinated_field_rate",
    "rejection_accuracy",
    "p50_latency_ms",
    "p95_latency_ms",
    "token_usage",
    "estimated_cost_per_request",
)


@dataclass(frozen=True)
class ModelContractPresence:
    provider: bool
    base_url: bool
    model_name: bool
    credential_ref: bool

    @property
    def complete(self) -> bool:
        return all((
            self.provider,
            self.base_url,
            self.model_name,
            self.credential_ref,
        ))

    def as_dict(self) -> dict[str, bool]:
        return {
            "provider_present": self.provider,
            "base_url_present": self.base_url,
            "model_name_present": self.model_name,
            "credential_ref_present": self.credential_ref,
        }


def runtime_smoke_cases(
    *,
    charging_min_date: str,
    charging_max_date: str,
    sales_min_date: str,
    sales_max_date: str,
) -> list[dict[str, str]]:
    return [
        {
            "case_id": "RSM-CH-001",
            "scenario": "charging_ops",
            "question": (
                f"查询模拟数据有效期 {charging_min_date} 至 "
                f"{charging_max_date} 内最近30天充电收入趋势。"
            ),
        },
        {
            "case_id": "RSM-CH-002",
            "scenario": "charging_ops",
            "question": (
                f"按区域统计 {charging_min_date} 至 {charging_max_date} "
                "的充电收入和订单量。"
            ),
        },
        {
            "case_id": "RSM-CH-003",
            "scenario": "charging_ops",
            "question": (
                f"查询 {charging_min_date} 至 {charging_max_date} "
                "充电收入最高的10个场站。"
            ),
        },
        {
            "case_id": "RSM-CH-004",
            "scenario": "charging_ops",
            "question": (
                f"查询 {charging_min_date} 至 {charging_max_date} "
                "设备利用率最低的场站。"
            ),
        },
        {
            "case_id": "RSM-CH-005",
            "scenario": "charging_ops",
            "question": (
                f"分析 {charging_min_date} 至 {charging_max_date} "
                "充电量和充电收入的关系。"
            ),
        },
        {
            "case_id": "RSM-SA-001",
            "scenario": "sales_ops",
            "question": (
                f"查询模拟数据有效期 {sales_min_date} 至 "
                f"{sales_max_date} 内最近30天销售收入。"
            ),
        },
        {
            "case_id": "RSM-SA-002",
            "scenario": "sales_ops",
            "question": (
                f"按渠道统计 {sales_min_date} 至 {sales_max_date} "
                "的销售收入。"
            ),
        },
        {
            "case_id": "RSM-SA-003",
            "scenario": "sales_ops",
            "question": (
                f"查询 {sales_min_date} 至 {sales_max_date} "
                "销售收入最高的10个商品。"
            ),
        },
        {
            "case_id": "RSM-SA-004",
            "scenario": "sales_ops",
            "question": (
                f"查询 {sales_min_date} 至 {sales_max_date} "
                "退款率最高的商品分类。"
            ),
        },
        {
            "case_id": "RSM-SA-005",
            "scenario": "sales_ops",
            "question": (
                f"按区域统计 {sales_min_date} 至 {sales_max_date} "
                "的客户数和订单量。"
            ),
        },
    ]


def build_blocked_runtime_report(
    golden_source: dict[str, Any],
    *,
    model_contract: ModelContractPresence,
    runtime_blocker: str | None = None,
    charging_min_date: str,
    charging_max_date: str,
    sales_min_date: str,
    sales_max_date: str,
) -> dict[str, Any]:
    """Build fail-closed evidence without contacting a model or SQLBot."""
    cases = golden_source.get("cases")
    if not isinstance(cases, list) or len(cases) != 100:
        raise ValueError("runtime Golden Set must contain exactly 100 cases")

    allowed_blockers = {
        "HUMAN_MODEL_CONFIG_REQUIRED",
        "LIVE_EXECUTION_REQUIRED",
        "PROVIDER_AUTHENTICATION_FAILED",
    }
    blocker = runtime_blocker or (
        "HUMAN_MODEL_CONFIG_REQUIRED"
        if not model_contract.complete
        else "LIVE_EXECUTION_REQUIRED"
    )
    if blocker not in allowed_blockers:
        raise ValueError("runtime blocker is not allowlisted")
    smoke = runtime_smoke_cases(
        charging_min_date=charging_min_date,
        charging_max_date=charging_max_date,
        sales_min_date=sales_min_date,
        sales_max_date=sales_max_date,
    )
    smoke_results = [
        {
            **case,
            "normalized_question": case["question"],
            "model": None,
            "sqlbot_session": None,
            "generated_sql": None,
            "guard_result": "NOT_EXECUTED",
            "execution_status": "NOT_EXECUTED",
            "row_count": None,
            "result_hash": None,
            "latency_ms": None,
            "token_usage": None,
            "dataset_version": None,
            "semantic_version": None,
            "run_id": None,
            "trace_id": None,
            "error": blocker,
        }
        for case in smoke
    ]
    golden_results = [
        {
            "case_id": case.get("case_id"),
            "scenario": case.get("scenario_id"),
            "contract_status": "NOT_REEVALUATED",
            "model_called": False,
            "sql_generated": False,
            "sql_guard_pass": None,
            "execution_attempted": False,
            "execution_pass": None,
            "result_match": None,
            "permission_pass": None,
            "final_status": "NOT_EXECUTED",
            "error": blocker,
        }
        for case in cases
    ]
    return {
        "evidence_type": "runtime_execution_blocker",
        "data_classification": "simulated",
        "model_contract": model_contract.as_dict(),
        "runtime_status": blocker,
        "model_called": False,
        "mock_provider_used": False,
        "external_request_count": 0,
        "unauthorized_model_context_send_count": 0,
        "smoke": {
            "status": "NOT_EXECUTED",
            "total": len(smoke_results),
            "executed": 0,
            "not_executed": len(smoke_results),
            "results": smoke_results,
        },
        "golden": {
            "evaluation_set": golden_source.get("name"),
            "evaluation_version": golden_source.get("version"),
            "status": "NOT_EXECUTED",
            "total": len(golden_results),
            "executed": 0,
            "not_executed": len(golden_results),
            "metrics": {
                metric: None for metric in RUNTIME_METRIC_NAMES
            },
            "scenario_metrics": {
                "charging_ops": None,
                "sales_ops": None,
            },
            "results": golden_results,
        },
        "shadow": {
            "status": "NOT_EXECUTED",
            "required": 20,
            "executed": 0,
        },
        "canary": {
            "eligible": False,
            "blockers": [
                blocker,
                "RUNTIME_SMOKE_NOT_EXECUTED",
                "RUNTIME_GOLDEN_NOT_EXECUTED",
                "REAL_SHADOW_NOT_EXECUTED",
            ],
        },
    }
