import re
from datetime import date
from time import perf_counter
from uuid import uuid4

from sqlalchemy.orm import Session

from app.platform.query_engine import QueryContext, QueryEngine, QueryRequest, QueryResult
from app.scenarios.sales_ops.metrics import SALES_METRICS, SalesOpsMetricService

METRIC_ALIASES = {
    "sales_revenue": ("销售收入", "销售额", "营收", "sales revenue"),
    "order_count": ("订单数", "单量", "order count"),
    "customer_count": ("客户数", "customer count"),
    "average_order_value": ("客单价", "平均订单金额", "average order"),
    "sales_quantity": ("销售数量", "销量", "quantity"),
    "gross_profit": ("销售毛利", "毛利", "gross profit"),
    "gross_margin": ("销售毛利率", "毛利率", "gross margin"),
    "refund_amount": ("退款金额", "refund amount"),
    "refund_rate": ("退款率", "refund rate"),
    "new_customer_count": ("新客户数", "new customer"),
    "repeat_customer_count": ("复购客户数", "老客户数", "repeat customer"),
    "channel_contribution": ("渠道贡献", "channel contribution"),
}


class SalesOpsQueryError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _metrics_from_question(question: str) -> tuple[str, ...]:
    lowered = question.lower()
    metrics = [
        code
        for code, aliases in METRIC_ALIASES.items()
        if any(alias.lower() in lowered for alias in aliases)
    ]
    if "gross_margin" in metrics and "gross_profit" in metrics:
        if "毛利额" not in question and "gross profit" not in lowered:
            metrics.remove("gross_profit")
    if not metrics:
        raise SalesOpsQueryError(
            "METRIC_AMBIGUOUS",
            "请明确销售指标，例如销售收入、订单数或毛利率。",
        )
    return tuple(metrics)


def _date_range(question: str) -> tuple[date, date]:
    iso_dates = re.findall(r"\d{4}-\d{2}-\d{2}", question)
    if len(iso_dates) >= 2:
        start, end = date.fromisoformat(iso_dates[0]), date.fromisoformat(iso_dates[1])
        return start, end
    chinese_range = re.search(
        r"(20\d{2})年(1[0-2]|[1-9])月(3[01]|[12]\d|[1-9])日?\s*"
        r"(?:至|到|~|—)\s*"
        r"(20\d{2})年(1[0-2]|[1-9])月(3[01]|[12]\d|[1-9])日?",
        question,
    )
    if chinese_range:
        values = tuple(map(int, chinese_range.groups()))
        start = date(values[0], values[1], values[2])
        end_inclusive = date(values[3], values[4], values[5])
        return start, end_inclusive + date.resolution
    month = re.search(r"(\d{4})年(1[0-2]|[1-9])月", question)
    if month:
        year, month_number = int(month.group(1)), int(month.group(2))
        start = date(year, month_number, 1)
        end = date(year + 1, 1, 1) if month_number == 12 else date(year, month_number + 1, 1)
        return start, end
    raise SalesOpsQueryError(
        "TIME_RANGE_AMBIGUOUS",
        "请明确当前 ACTIVE 数据集范围内的月份或开始、结束日期。",
    )


def _region_scope(request: QueryRequest) -> tuple[str, ...] | None:
    if "workspace:all" in request.identity_context.data_scopes:
        return None
    regions = tuple(
        scope.split(":", 1)[1]
        for scope in request.identity_context.data_scopes
        if scope.startswith("region:")
    )
    if not regions:
        raise SalesOpsQueryError("AUTH_SCOPE_DENIED", "当前身份没有销售区域权限")
    requested = tuple(sorted(set(re.findall(r"\bR0[1-8]\b", request.question.upper()))))
    if requested and not set(requested).issubset(regions):
        raise SalesOpsQueryError("AUTH_SCOPE_DENIED", "请求销售区域超出授权范围")
    return requested or regions


class SalesOpsDeterministicEngine(QueryEngine):
    name = "deterministic"
    version = "sales-ops-1.0.0"

    def __init__(self, db: Session):
        self.db = db

    def execute(
        self,
        request: QueryRequest,
        context: QueryContext | None = None,
    ) -> QueryResult:
        if request.scenario_id != "sales_ops":
            raise SalesOpsQueryError("SCENARIO_MISMATCH", "销售引擎拒绝跨场景请求")
        if context is None or context.scenario_version != "1.0.0":
            raise SalesOpsQueryError("VERSION_NOT_ACTIVE", "sales_ops ACTIVE 版本不可用")
        started_at = perf_counter()
        metrics = _metrics_from_question(request.question)
        start, end_exclusive = _date_range(request.question)
        period_start = (
            date.fromisoformat(context.prompt_context["dataset_period_start"])
            if context.prompt_context.get("dataset_period_start")
            else date(2025, 1, 1)
        )
        period_end_exclusive = (
            date.fromisoformat(context.prompt_context["dataset_period_end_exclusive"])
            if context.prompt_context.get("dataset_period_end_exclusive")
            else date(2026, 7, 1)
        )
        if start < period_start or end_exclusive > period_end_exclusive:
            raise SalesOpsQueryError("OUT_OF_DATA_RANGE", "请求超出当前 ACTIVE 销售数据范围")
        all_values = SalesOpsMetricService(self.db).calculate(
            start,
            end_exclusive,
            region_ids=_region_scope(request),
        )
        values = {code: all_values[code] for code in metrics}
        run_id = context.run_id or f"SALES-{uuid4()}"
        return QueryResult(
            engine=self.name,
            engine_version=self.version,
            scenario="sales_ops",
            scenario_version=context.scenario_version,
            semantic_version=context.semantic_version,
            dataset_version=context.dataset_version,
            sql=None,
            columns=tuple(values),
            rows=(values,),
            chart_spec=(
                {
                    "type": "bar",
                    "metrics": list(values),
                    "data": [values],
                }
                if len(values) > 1
                else None
            ),
            evidence={
                "data_classification": context.data_classification,
                "source": "platform_database",
                "query_guard": "passed",
                "answer_guard": "passed",
                "metric_values": values,
                "time_range": [start.isoformat(), end_exclusive.isoformat()],
                "dimensions": [],
                "scenario_version": context.scenario_version,
                "semantic_version": context.semantic_version,
                "semantic_model_version_id": context.semantic_model_version_id,
                "dataset_version": context.dataset_version,
                "dataset_version_id": context.dataset_version_id,
            },
            warnings=(),
            execution_time=int((perf_counter() - started_at) * 1000),
            trace_id=request.identity_context.request_id,
            run_id=run_id,
            status="completed",
        )

    def health_check(self) -> dict:
        return {
            "engine": self.name,
            "version": self.version,
            "scenario": "sales_ops",
            "status": "ok",
        }
