import re
from typing import Any

import sqlglot
from sqlglot import exp

from app.chatbi.compiler import CompiledQuery

ALLOWED_TABLES = {"fact_charging_session", "fact_energy_cost", "fact_operation_expense", "fact_device_status_event", "dim_station"}
FORBIDDEN_NODES = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter, exp.Command, exp.Merge)
REQUIRED_PARAMETERS = {"start_ts", "end_ts", "start_date", "end_date", "period_seconds", "limit"}


class QueryRejected(ValueError):
    pass


def guard_compiled_query(compiled: CompiledQuery) -> None:
    sql = compiled.sql
    if "--" in sql or "/*" in sql or "*/" in sql:
        raise QueryRejected("comments are forbidden")
    statements = sqlglot.parse(sql, read="postgres")
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        raise QueryRejected("exactly one SELECT statement is required")
    root = statements[0]
    if any(root.find(node) is not None for node in FORBIDDEN_NODES):
        raise QueryRejected("write or control statement rejected")
    tables = {table.name for table in root.find_all(exp.Table)}
    if not tables.issubset(ALLOWED_TABLES | {"s", "e", "o", "st", "ds"}):
        raise QueryRejected("table is not allowlisted")
    if re.search(r"(?i)\b(pg_catalog|information_schema|pg_read_file|pg_sleep|dblink)\b", sql):
        raise QueryRejected("forbidden object or function")
    if not REQUIRED_PARAMETERS.issubset(compiled.parameters):
        raise QueryRejected("required server parameters missing")
    if not compiled.station_ids or not all(compiled.parameters.get(f"station_{i}") == value for i, value in enumerate(compiled.station_ids)):
        raise QueryRejected("authorization scope parameters missing")
    if compiled.parameters["limit"] > 5000:
        raise QueryRejected("row limit exceeds hard cap")


def reject_arbitrary_sql(sql: str) -> None:
    """Negative-test boundary: no external SQL is accepted by the product API."""
    try:
        statements = sqlglot.parse(sql, read="postgres")
    except sqlglot.errors.ParseError as exc:
        raise QueryRejected("unparseable SQL") from exc
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        raise QueryRejected("arbitrary SQL rejected")
    raise QueryRejected("external SQL is never an executable input")


def guard_sqlbot_sql(sql: str, context: Any) -> None:
    """Validate SQLBot output against the active semantic-view contract."""
    if not sql or "--" in sql or "/*" in sql or "*/" in sql:
        raise QueryRejected("SQLBot SQL contains forbidden comments or is empty")
    try:
        statements = sqlglot.parse(sql, read="postgres")
    except sqlglot.errors.ParseError as exc:
        raise QueryRejected("SQLBot SQL is not parseable") from exc
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        raise QueryRejected("SQLBot must produce exactly one SELECT")
    root = statements[0]
    if root.find(exp.With) is not None:
        raise QueryRejected("SQLBot common table expressions are not enabled")
    if any(root.find(node) is not None for node in FORBIDDEN_NODES):
        raise QueryRejected("SQLBot write or control statement rejected")
    if root.find(exp.Star) is not None:
        raise QueryRejected("SQLBot wildcard projection is forbidden")
    if re.search(
        r"(?i)\b(pg_catalog|information_schema|pg_read_file|pg_sleep|"
        r"dblink|lo_import|current_setting|set_config)\b",
        sql,
    ):
        raise QueryRejected("SQLBot references a forbidden object or function")

    allowed_relations = context.allowed_relations
    if not isinstance(allowed_relations, dict) or not allowed_relations:
        raise QueryRejected("SQLBot semantic relation allowlist is empty")
    tables = {table.name for table in root.find_all(exp.Table)}
    if not tables or not tables.issubset(set(allowed_relations)):
        raise QueryRejected("SQLBot table is not in the active scenario allowlist")
    allowed_columns = {
        column
        for columns in allowed_relations.values()
        for column in columns
    }
    projected_aliases = {
        alias.alias
        for alias in root.find_all(exp.Alias)
        if alias.alias
    }
    referenced_columns = {column.name for column in root.find_all(exp.Column)}
    if referenced_columns - allowed_columns - projected_aliases:
        raise QueryRejected("SQLBot field is not in the active semantic allowlist")

    limit = root.args.get("limit")
    if limit is None:
        if root.find(exp.AggFunc) is not None or root.args.get("group") is not None:
            return
        raise QueryRejected("SQLBot detail result must have a literal LIMIT")
    if not isinstance(limit.expression, exp.Literal):
        raise QueryRejected("SQLBot result must have a literal LIMIT")
    try:
        requested_limit = int(limit.expression.this)
    except (TypeError, ValueError) as exc:
        raise QueryRejected("SQLBot LIMIT is invalid") from exc
    if requested_limit < 1 or requested_limit > int(context.max_rows):
        raise QueryRejected("SQLBot LIMIT exceeds the active policy")
