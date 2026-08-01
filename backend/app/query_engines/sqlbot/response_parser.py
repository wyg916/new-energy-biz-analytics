from __future__ import annotations

import json
import re
from typing import Any

import sqlglot
from sqlglot import exp

from app.query_engines.sqlbot.contracts import SQLBotParsedResponse
from app.query_engines.sqlbot.error_mapper import (
    SQLBotEngineError,
    SQLBotErrorCode,
)


_ENVELOPE_KEYS = ("data", "result", "payload")
_TEXT_KEYS = ("content", "message", "answer", "sql_answer")
_JSON_FENCE = re.compile(r"\A\s*```json\s*(.*?)\s*```\s*\Z", re.IGNORECASE | re.DOTALL)
_SQL_FENCE = re.compile(
    r"\A\s*```(?:sql|postgres|postgresql)\s*(.*?)\s*```\s*\Z",
    re.IGNORECASE | re.DOTALL,
)


def _json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _find_explicit_sql_mapping(value: Any) -> dict[str, Any] | None:
    """Find only documented JSON/envelope fields; never scan arbitrary prose."""
    value = _json(value)
    if isinstance(value, dict):
        if isinstance(value.get("sql"), str) and value["sql"].strip():
            return value
        for key in _ENVELOPE_KEYS:
            nested = _find_explicit_sql_mapping(value.get(key))
            if nested is not None:
                return nested
    if isinstance(value, list):
        for item in reversed(value):
            nested = _find_explicit_sql_mapping(item)
            if nested is not None:
                return nested
    return None


def _approved_text_values(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, dict):
        return ()
    values: list[str] = []
    for key in _TEXT_KEYS:
        item = value.get(key)
        if isinstance(item, str):
            values.append(item)
    for key in _ENVELOPE_KEYS:
        values.extend(_approved_text_values(value.get(key)))
    return tuple(values)


def _single_select_text(value: str) -> str | None:
    sql = value.strip()
    if not sql:
        return None
    try:
        statements = sqlglot.parse(sql, read="postgres")
    except sqlglot.errors.ParseError:
        return None
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        return None
    return sql[:-1].rstrip() if sql.endswith(";") else sql


def _candidate_in_order(payload: Any) -> tuple[dict[str, Any] | None, str | None]:
    # 1. Standard JSON object or JSON string.
    decoded = _json(payload)
    standard = _find_explicit_sql_mapping(decoded)
    if standard is not None:
        return standard, "standard_json"

    texts = _approved_text_values(payload)

    # 2. A complete JSON code block in a documented response field.
    for value in texts:
        match = _JSON_FENCE.fullmatch(value)
        if match:
            candidate = _find_explicit_sql_mapping(_json(match.group(1)))
            if candidate is not None:
                return candidate, "json_code_block"

    # 3. A complete SQL code block. Prose surrounding the block is rejected.
    for value in texts:
        match = _SQL_FENCE.fullmatch(value)
        if match:
            sql = _single_select_text(match.group(1))
            if sql is not None:
                return {"sql": sql}, "sql_code_block"

    # 4. A complete single SELECT text. Embedded/narrated SQL is rejected.
    for value in texts:
        sql = _single_select_text(value)
        if sql is not None:
            return {"sql": sql}, "single_select_text"

    # 5. SQLBot v1.8 ChatRecord fields. sql is authoritative; sql_answer is
    # accepted only when it is itself one of the strict formats above.
    if isinstance(payload, dict):
        record = payload.get("record")
        if isinstance(record, dict):
            sql = record.get("sql")
            if isinstance(sql, str) and sql.strip():
                return record, "sqlbot_record"
            sql_answer = record.get("sql_answer")
            if isinstance(sql_answer, str):
                decoded_answer = _find_explicit_sql_mapping(_json(sql_answer))
                if decoded_answer is not None:
                    return {**record, **decoded_answer}, "sqlbot_record"
                for pattern in (_JSON_FENCE, _SQL_FENCE):
                    match = pattern.fullmatch(sql_answer)
                    if match:
                        nested = (
                            _find_explicit_sql_mapping(_json(match.group(1)))
                            if pattern is _JSON_FENCE
                            else {"sql": _single_select_text(match.group(1))}
                        )
                        if nested is not None and nested.get("sql"):
                            return {**record, **nested}, "sqlbot_record"
                plain = _single_select_text(sql_answer)
                if plain is not None:
                    return {**record, "sql": plain}, "sqlbot_record"
    return None, None


def _field_names(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    names = []
    for item in value:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict):
            name = item.get("name") or item.get("field") or item.get("value")
            if isinstance(name, str):
                names.append(name)
    return tuple(names)


def _normalize_rows(value: Any) -> tuple[dict[str, Any], ...]:
    value = _json(value)
    if isinstance(value, dict):
        fields = _field_names(value.get("fields") or value.get("columns"))
        raw_rows = value.get("rows", value.get("data", value.get("records", value.get("result"))))
        raw_rows = _json(raw_rows)
        if fields and isinstance(raw_rows, list):
            converted = []
            for row in raw_rows:
                if isinstance(row, dict):
                    converted.append(row)
                elif isinstance(row, (list, tuple)) and len(row) == len(fields):
                    converted.append(dict(zip(fields, row, strict=True)))
            return tuple(converted)
        if raw_rows is not None:
            return _normalize_rows(raw_rows)
        return (value,)
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, dict))


def parse_response(payload: Any, *, max_rows: int) -> SQLBotParsedResponse:
    decoded = _json(payload)
    if isinstance(decoded, dict) and decoded.get("success") is False:
        raise SQLBotEngineError(
            SQLBotErrorCode.UPSTREAM_UNAVAILABLE,
            "SQLBot 未完成请求",
        )
    candidate, response_format = _candidate_in_order(payload)
    if candidate is None:
        raise SQLBotEngineError(
            SQLBotErrorCode.RESPONSE_INVALID,
            "SQLBot 响应不符合受支持的结构化 SQL 格式",
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
    columns = tuple(rows[0]) if rows else _field_names(candidate.get("columns") or candidate.get("fields"))
    chart = _json(candidate.get("chart") or candidate.get("chart_spec"))
    if chart is not None and not isinstance(chart, dict):
        chart = None
    token_usage = candidate.get("token_usage")
    if token_usage is None and isinstance(decoded, dict):
        token_usage = decoded.get("token_usage")
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
        warnings=(f"sqlbot_response_format:{response_format}",),
    )
