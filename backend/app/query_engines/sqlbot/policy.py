from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import sqlglot
from sqlglot import exp

from app.platform.query_engine import QueryContext
from app.query_engines.sqlbot.error_mapper import SQLBotEngineError, SQLBotErrorCode


FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter,
    exp.Command, exp.Merge, exp.Transaction,
)
FORBIDDEN_OBJECT = re.compile(
    r"(?i)\b(pg_catalog|information_schema|pg_read_file|pg_sleep|dblink|"
    r"lo_import|current_setting|set_config|copy|vacuum|analyze)\b"
)
PII_COLUMN = re.compile(
    r"(?i)(password|passwd|token|secret|phone|mobile|email|id_card|identity|"
    r"customer_name|user_name|address|bank_account)"
)


@dataclass(frozen=True)
class SQLPolicyDecision:
    normalized_sql: str
    relations: tuple[str, ...]
    columns: tuple[str, ...]
    join_count: int
    row_limit: int | None
    checks: tuple[str, ...]


def _deny(message: str) -> None:
    raise SQLBotEngineError(SQLBotErrorCode.POLICY_DENIED, message)


def _relationship_pairs(context: QueryContext) -> set[frozenset[tuple[str, str]]]:
    allowed: set[frozenset[tuple[str, str]]] = set()
    for item in (context.prompt_context or {}).get("relationships", []):
        source = item.get("source_table")
        target = item.get("target_table")
        source_fields = item.get("source_fields") or ()
        target_fields = item.get("target_fields") or ()
        for left, right in zip(source_fields, target_fields):
            allowed.add(frozenset(((str(source), str(left)), (str(target), str(right)))))
    return allowed


def validate_generated_sql(sql: str, context: QueryContext) -> SQLPolicyDecision:
    if not sql or any(marker in sql for marker in ("--", "/*", "*/")):
        _deny("generated SQL is empty or contains comments")
    try:
        statements = sqlglot.parse(sql, read="postgres")
    except sqlglot.errors.ParseError as exc:
        raise SQLBotEngineError(SQLBotErrorCode.RESPONSE_INVALID, "generated SQL is not parseable") from exc
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        _deny("exactly one SELECT statement is required")
    root = statements[0]
    if any(root.find(node) is not None for node in FORBIDDEN_NODES):
        _deny("write or control statement rejected")
    if root.find(exp.With) is not None or root.find(exp.Union) is not None:
        _deny("CTE and set operations are outside the controlled NL2SQL scope")
    if root.find(exp.Star) is not None:
        _deny("wildcard projection is forbidden")
    if FORBIDDEN_OBJECT.search(sql):
        _deny("forbidden object or function referenced")

    allowed_relations = context.allowed_relations
    if not allowed_relations:
        _deny("active semantic relation allowlist is empty")
    table_aliases: dict[str, str] = {}
    relations = []
    for table in root.find_all(exp.Table):
        if table.catalog or table.db:
            _deny("cross-database or explicit schema access is forbidden")
        if table.name not in allowed_relations:
            _deny("relation is not registered for the active scenario")
        relations.append(table.name)
        table_aliases[table.alias_or_name] = table.name
    if not relations:
        _deny("query must reference a registered relation")

    projected_aliases = {alias.alias for alias in root.find_all(exp.Alias) if alias.alias}
    columns: list[str] = []
    for column in root.find_all(exp.Column):
        name = column.name
        if PII_COLUMN.search(name):
            _deny("sensitive or PII column is forbidden")
        if name in projected_aliases and not column.table:
            continue
        if column.table:
            relation = table_aliases.get(column.table)
            if relation is None or name not in allowed_relations.get(relation, ()):
                _deny("qualified field is not in the active semantic allowlist")
        else:
            matches = [relation for relation in relations if name in allowed_relations[relation]]
            if len(set(matches)) != 1:
                _deny("unqualified field is unknown or ambiguous")
        columns.append(name)

    joins = tuple(root.find_all(exp.Join))
    if len(joins) > 4:
        _deny("join count exceeds the controlled cost budget")
    relationship_pairs = _relationship_pairs(context)
    for join in joins:
        if join.args.get("on") is None or join.args.get("kind") == "CROSS":
            _deny("every join requires an approved equality predicate")
        predicates = tuple(join.args["on"].find_all(exp.EQ))
        if not predicates:
            _deny("join predicate must contain an equality")
        for predicate in predicates:
            left, right = predicate.left, predicate.right
            if not isinstance(left, exp.Column) or not isinstance(right, exp.Column):
                _deny("join equality must compare registered columns")
            pair = frozenset((
                (table_aliases.get(left.table, left.table), left.name),
                (table_aliases.get(right.table, right.table), right.name),
            ))
            if pair not in relationship_pairs:
                _deny("join relationship is not published")

    for function in root.find_all(exp.Func):
        name = function.sql_name().lower()
        if name in {"pg_sleep", "current_setting", "set_config", "lo_import"}:
            _deny("unsafe function is forbidden")
    limit_node = root.args.get("limit")
    row_limit = None
    if limit_node is not None:
        literal = limit_node.expression
        if not isinstance(literal, exp.Literal) or not literal.is_int:
            _deny("LIMIT must be a positive integer literal")
        row_limit = int(literal.this)
        if not 1 <= row_limit <= int(context.max_rows):
            _deny("LIMIT exceeds the active row policy")
    elif root.find(exp.AggFunc) is None and root.args.get("group") is None:
        _deny("detail query requires a bounded LIMIT")

    return SQLPolicyDecision(
        normalized_sql=root.sql(dialect="postgres"),
        relations=tuple(sorted(set(relations))),
        columns=tuple(sorted(set(columns))),
        join_count=len(joins),
        row_limit=row_limit,
        checks=(
            "parser_ast", "schema", "join", "permission", "pii",
            "cost", "row_limit", "query_guard", "readonly_boundary",
        ),
    )
