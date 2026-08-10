from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.platform.query_engine import QueryContext, QueryRequest


_HIGH_RISK = re.compile(
    r"(?i)(ignore\s+(permission|policy)|bypass|password|token|secret|"
    r"customer_name|phone|email|identity|all\s+users|"
    r"\b(insert|update|delete|drop|alter|truncate)\b|system\s+tables?|"
    r"忽略.*(权限|规则)|绕过|密码|密钥|手机号|身份证|客户.*姓名|全部用户|"
    r"真实客户|不用指标口径|随便算|跨到.*场景|另一个场景|执行写入|"
    r"改成零|删除|修改.*表结构|查询和删除|系统表|返回全部行)"
)
_OPEN_EXPLORATION = re.compile(
    r"(?i)(schema|field|column|table|distribution|detail|sample|"
    r"字段|列|表|分布|明细|样本|组合|交叉|关联)"
)
_VAGUE_TIME = re.compile(r"(?i)(最近|近期|当前|本期|lately|recently|current period)")
_OUT_OF_RANGE_TIME = re.compile(r"(?i)(明年|未来|next\s+(year|quarter|month))")
_BOUNDED_RELATIVE_TIME = re.compile(
    r"(?i)(最近\s*\d+\s*(天|日|周|月|季度|年)|last\s+\d+\s+(day|week|month|quarter|year)s?)"
)
_VAGUE_QUALITY = re.compile(
    r"(?i)(怎么样|表现如何|经营如何|销售表现|哪个.*最好|哪家.*最好|best|performance)"
)
_ENTITY_PRONOUN = re.compile(r"(?i)(这个|那个|上述|上一个|它的|该对象|that one|previous one)")
_SCOPE_CONFLICT = re.compile(
    r"(?i)((仅|只看).*(全部|所有)|(全部|所有).*(仅|只看)|跨租户|其他租户|超出.*权限)"
)
_COMPARISON = re.compile(r"(?i)(比较|对比|变化|差异|compare|change|difference)")
_DEFINED_COMPARISON = re.compile(r"(?i)(环比|同比|较|相比|versus|\bvs\.?\b|mom|yoy)")
_EXPLICIT_TIME = re.compile(
    r"(?i)(?:20\d{2}年|\d{4}-\d{2}-\d{2}|上半年|下半年|季度|月份|每月|按月|同比|环比)"
)

# These hints close lexical gaps in the published Chinese labels without
# introducing new metrics, relations, or database values.  Every key must be a
# code from the active semantic release; unmatched hints therefore cannot
# expand the schema allowlist on their own.
_CONTROLLED_SEMANTIC_HINTS: dict[str, tuple[str, ...]] = {
    "completed_order_count": ("订单", "完成订单"),
    "order_count": ("订单",),
    "sales_revenue": ("收入",),
    "gross_profit": ("毛利",),
    "new_customer_count": ("新客户",),
    "repeat_customer_count": ("复购客户",),
    "station": ("快充站", "慢充站", "站点"),
    "station_type": ("快充", "慢充"),
    "customer_segment": ("企业客户", "政府客户", "消费客户", "小微客户"),
}


@dataclass(frozen=True)
class QueryUnderstanding:
    route_class: str
    risk: str
    deterministic_preferred: bool
    reason: str
    status: str = "READY"
    clarification_codes: tuple[str, ...] = ()
    clarification_question: str | None = None
    matched_metrics: tuple[str, ...] = ()
    matched_dimensions: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "route_class": self.route_class,
            "risk": self.risk,
            "deterministic_preferred": self.deterministic_preferred,
            "reason": self.reason,
            "clarification_codes": list(self.clarification_codes),
            "clarification_question": self.clarification_question,
            "matched_metrics": list(self.matched_metrics),
            "matched_dimensions": list(self.matched_dimensions),
        }


def _compact(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", value.lower())


def _item_matches(question: str, item: dict[str, Any]) -> bool:
    compact_question = _compact(question)
    values = (item.get("code"), item.get("name"), *(item.get("aliases") or ()))
    label_match = any(
        isinstance(value, str)
        and len(_compact(value)) >= 2
        and _compact(value) in compact_question
        for value in values
    )
    hints = _CONTROLLED_SEMANTIC_HINTS.get(str(item.get("code") or ""), ())
    return label_match or any(_compact(hint) in compact_question for hint in hints)


def understand_query(request: QueryRequest, context: QueryContext) -> QueryUnderstanding:
    question = request.question.strip()
    if _HIGH_RISK.search(question):
        return QueryUnderstanding(
            "high_risk",
            "high",
            True,
            "high_risk_request",
            status="REJECTED",
        )
    prompt = context.prompt_context or {}
    matched_metrics = tuple(
        str(item.get("code"))
        for item in prompt.get("metrics", ())
        if isinstance(item, dict) and item.get("code") and _item_matches(question, item)
    )
    matched_dimensions = tuple(
        str(item.get("code"))
        for item in prompt.get("dimensions", ())
        if isinstance(item, dict) and item.get("code") and _item_matches(question, item)
    )
    if _EXPLICIT_TIME.search(question):
        published_dimension_codes = {
            str(item.get("code"))
            for item in prompt.get("dimensions", ())
            if isinstance(item, dict) and item.get("code")
        }
        if "date" in published_dimension_codes and "date" not in matched_dimensions:
            matched_dimensions = (*matched_dimensions, "date")
    clarification_codes: list[str] = []
    if "充电" in question and "销售" in question:
        clarification_codes.append("SCENARIO_AMBIGUITY")
    if _VAGUE_TIME.search(question) and not _BOUNDED_RELATIVE_TIME.search(question):
        clarification_codes.append("TIME_AMBIGUITY")
    if _OUT_OF_RANGE_TIME.search(question):
        clarification_codes.append("TIME_OUT_OF_DATA_RANGE")
    if _VAGUE_QUALITY.search(question) and not matched_metrics:
        clarification_codes.append("METRIC_AMBIGUITY")
    if _ENTITY_PRONOUN.search(question) and not request.conversation_state.get("resolved_entity"):
        clarification_codes.append("ENTITY_AMBIGUITY")
    if _SCOPE_CONFLICT.search(question):
        clarification_codes.append("REQUEST_SCOPE_CONFLICT")
    if (
        _COMPARISON.search(question)
        and not _DEFINED_COMPARISON.search(question)
        and len(matched_metrics) < 2
        and not matched_dimensions
    ):
        clarification_codes.append("MISSING_COMPARISON_CONDITION")
    if clarification_codes:
        codes = tuple(dict.fromkeys(clarification_codes))
        return QueryUnderstanding(
            "needs_clarification",
            "controlled",
            True,
            "clarification_gate",
            status="NEEDS_CLARIFICATION",
            clarification_codes=codes,
            clarification_question="请明确指标、时间范围、比较对象和授权范围后再查询。",
            matched_metrics=matched_metrics,
            matched_dimensions=matched_dimensions,
        )
    if matched_metrics and not _OPEN_EXPLORATION.search(question):
        return QueryUnderstanding(
            "core_metric", "controlled", True, "core_metric_pinned",
            matched_metrics=matched_metrics,
            matched_dimensions=matched_dimensions,
        )
    return QueryUnderstanding(
        "governed_open_nl2sql", "controlled", False,
        "registered_schema_exploration",
        matched_metrics=matched_metrics,
        matched_dimensions=matched_dimensions,
    )
