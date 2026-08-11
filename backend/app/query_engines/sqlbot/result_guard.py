from __future__ import annotations

import math
from typing import Any

from app.platform.query_engine import QueryContext
from app.query_engines.sqlbot.error_mapper import SQLBotEngineError, SQLBotErrorCode
from app.query_engines.sqlbot.policy import SQLPolicyDecision


def validate_result(
    columns: tuple[str, ...],
    rows: tuple[dict[str, Any], ...],
    context: QueryContext,
    decision: SQLPolicyDecision,
) -> dict[str, Any]:
    if len(rows) > context.max_rows:
        raise SQLBotEngineError(SQLBotErrorCode.POLICY_DENIED, "result exceeds the active row policy")
    if len(columns) != len(set(columns)) or any(not isinstance(column, str) for column in columns):
        raise SQLBotEngineError(SQLBotErrorCode.RESPONSE_INVALID, "result columns are invalid")
    for row in rows:
        if set(row) != set(columns):
            raise SQLBotEngineError(SQLBotErrorCode.RESPONSE_INVALID, "result row shape is inconsistent")
        for value in row.values():
            if isinstance(value, float) and not math.isfinite(value):
                raise SQLBotEngineError(SQLBotErrorCode.RESPONSE_INVALID, "result contains non-finite numbers")
    return {
        "status": "passed",
        "row_count": len(rows),
        "column_count": len(columns),
        "grounded_number_count": sum(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for row in rows for value in row.values()
        ),
        "policy_checks": list(decision.checks),
    }
