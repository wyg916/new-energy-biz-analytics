from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp

from app.query_engines.sqlbot.error_mapper import SQLBotEngineError, SQLBotErrorCode


PLATFORM_MAX_LIMIT = 500
DEFAULT_DETAIL_LIMIT = 100


@dataclass(frozen=True)
class LimitPolicyResult:
    sql: str
    warnings: tuple[str, ...]


def is_aggregate_query(root: exp.Expression) -> bool:
    return root.find(exp.AggFunc) is not None or root.args.get("group") is not None


def apply_limit_policy(
    sql: str,
    *,
    max_limit: int = PLATFORM_MAX_LIMIT,
    default_detail_limit: int = DEFAULT_DETAIL_LIMIT,
) -> LimitPolicyResult:
    """Apply row policy to the SQL AST without unsafe string replacement."""
    hard_limit = min(max(int(max_limit), 1), PLATFORM_MAX_LIMIT)
    detail_limit = min(max(int(default_detail_limit), 1), hard_limit)
    try:
        statements = sqlglot.parse(sql, read="postgres")
    except sqlglot.errors.ParseError as exc:
        raise SQLBotEngineError(
            SQLBotErrorCode.RESPONSE_INVALID,
            "SQLBot SQL 无法解析，不能应用 LIMIT 策略",
        ) from exc
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        return LimitPolicyResult(sql=sql.strip(), warnings=())

    root = statements[0]
    limit = root.args.get("limit")
    warnings: list[str] = []
    if limit is None:
        if not is_aggregate_query(root):
            root.set("limit", exp.Limit(expression=exp.Literal.number(detail_limit)))
            warnings.append(f"default_detail_limit_added:{detail_limit}")
    else:
        literal = limit.expression
        if not isinstance(literal, exp.Literal) or not literal.is_int:
            raise SQLBotEngineError(
                SQLBotErrorCode.POLICY_DENIED,
                "SQLBot LIMIT 必须是正整数常量",
            )
        requested = int(literal.this)
        if requested < 1:
            raise SQLBotEngineError(
                SQLBotErrorCode.POLICY_DENIED,
                "SQLBot LIMIT 必须大于零",
            )
        if requested > hard_limit:
            limit.set("expression", exp.Literal.number(hard_limit))
            warnings.append(f"limit_clamped:{requested}->{hard_limit}")
    return LimitPolicyResult(
        sql=root.sql(dialect="postgres"),
        warnings=tuple(warnings),
    )
