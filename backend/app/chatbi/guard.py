import re

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
