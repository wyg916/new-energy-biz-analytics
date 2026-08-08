from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.platform.query_engine import QueryContext, QueryRequest


_HIGH_RISK = re.compile(
    r"(?i)(ignore\s+(permission|policy)|bypass|password|token|secret|"
    r"customer_name|phone|email|identity|all\s+users|"
    r"忽略.*(权限|规则)|绕过|密码|密钥|手机号|身份证|客户姓名|全部用户)"
)
_OPEN_EXPLORATION = re.compile(
    r"(?i)(schema|field|column|table|distribution|detail|sample|"
    r"字段|列|表|分布|明细|样本|组合|交叉|关联)"
)


@dataclass(frozen=True)
class QueryUnderstanding:
    route_class: str
    risk: str
    deterministic_preferred: bool
    reason: str


def understand_query(request: QueryRequest, context: QueryContext) -> QueryUnderstanding:
    question = request.question.strip()
    if _HIGH_RISK.search(question):
        return QueryUnderstanding("high_risk", "high", True, "high_risk_request")
    prompt = context.prompt_context or {}
    searchable_metrics = json.dumps(prompt.get("metrics", []), ensure_ascii=False).lower()
    compact = re.sub(r"\s+", "", question.lower())
    metric_hit = any(
        token and token in compact
        for token in re.findall(r"[\w\u4e00-\u9fff]+", searchable_metrics)
        if len(token) >= 3
    )
    if metric_hit and not _OPEN_EXPLORATION.search(question):
        return QueryUnderstanding("core_metric", "controlled", True, "core_metric_pinned")
    return QueryUnderstanding("governed_open_nl2sql", "controlled", False, "registered_schema_exploration")
