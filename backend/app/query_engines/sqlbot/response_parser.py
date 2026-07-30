import json
from typing import Any

from app.query_engines.sqlbot.contracts import SQLBotParsedResponse
from app.query_engines.sqlbot.error_mapper import (
    SQLBotEngineError,
    SQLBotErrorCode,
)


def _decode_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _find_mapping_with_sql(value: Any) -> dict[str, Any] | None:
    value = _decode_json(value)
    if isinstance(value, dict):
        if isinstance(value.get("sql"), str):
            return value
        for key in ("data", "result", "record", "content", "payload"):
            nested = _find_mapping_with_sql(value.get(key))
            if nested is not None:
                return nested
    if isinstance(value, list):
        for item in reversed(value):
            nested = _find_mapping_with_sql(item)
            if nested is not None:
                return nested
    return None


def _normalize_rows(value: Any) -> tuple[dict[str, Any], ...]:
    value = _decode_json(value)
    if isinstance(value, dict):
        for key in ("rows", "data", "records", "result"):
            if key in value:
                return _normalize_rows(value[key])
        return (value,)
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, dict))


def parse_response(payload: Any, *, max_rows: int) -> SQLBotParsedResponse:
    payload = _decode_json(payload)
    if not isinstance(payload, dict):
        raise SQLBotEngineError(
            SQLBotErrorCode.RESPONSE_INVALID,
            "SQLBot 响应不是结构化对象",
        )
    if payload.get("success") is False:
        raise SQLBotEngineError(
            SQLBotErrorCode.UPSTREAM_UNAVAILABLE,
            "SQLBot 未完成请求",
        )
    candidate = _find_mapping_with_sql(payload)
    if candidate is None:
        raise SQLBotEngineError(
            SQLBotErrorCode.RESPONSE_INVALID,
            "SQLBot 响应缺少可审计 SQL",
        )
    sql = str(candidate["sql"]).strip()
    rows = _normalize_rows(
        candidate.get("rows", candidate.get("data", candidate.get("result")))
    )
    if len(rows) > max_rows:
        raise SQLBotEngineError(
            SQLBotErrorCode.POLICY_DENIED,
            "SQLBot 返回规模超过平台限制",
        )
    columns = tuple(rows[0]) if rows else tuple(candidate.get("columns") or ())
    chart = _decode_json(candidate.get("chart") or candidate.get("chart_spec"))
    if chart is not None and not isinstance(chart, dict):
        chart = None
    token_usage = candidate.get("token_usage", payload.get("token_usage"))
    if isinstance(token_usage, dict):
        token_usage = token_usage.get("total_tokens")
    if not isinstance(token_usage, int):
        token_usage = None
    record_id = candidate.get("record_id") or candidate.get("id")
    return SQLBotParsedResponse(
        sql=sql,
        columns=columns,
        rows=rows,
        chart_spec=chart,
        token_usage=token_usage,
        upstream_record_id=str(record_id) if record_id is not None else None,
    )
