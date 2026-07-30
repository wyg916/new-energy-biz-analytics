import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from app.platform.connectors.contracts import ColumnItem, DataBatch


def normalized_type(value: object) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, (float, Decimal)):
        return "number"
    if isinstance(value, datetime):
        return "datetime"
    if isinstance(value, date):
        return "date"
    if isinstance(value, (dict, list, tuple)):
        return "json"
    return "string"


def normalize_source_type(source_type: str) -> str:
    value = source_type.lower()
    if any(token in value for token in ("int", "serial")):
        return "integer"
    if any(token in value for token in ("numeric", "decimal", "real", "double", "float")):
        return "number"
    if "bool" in value:
        return "boolean"
    if "timestamp" in value or "datetime" in value:
        return "datetime"
    if value == "date":
        return "date"
    if any(token in value for token in ("json", "array")):
        return "json"
    if any(token in value for token in ("binary", "byte", "blob")):
        return "binary"
    return "string"


def jsonable(value: object) -> object:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.hex()
    return value


def make_batch(
    connector_id: str,
    columns: tuple[ColumnItem, ...],
    rows: list[dict],
    *,
    source_version: str,
    data_classification: str,
    cursor: str | None = None,
    next_offset: int | None = None,
) -> DataBatch:
    normalized_rows = tuple({key: jsonable(value) for key, value in row.items()} for row in rows)
    schema_payload = [(column.name, column.normalized_type, column.nullable) for column in columns]
    schema_fingerprint = hashlib.sha256(json.dumps(schema_payload, sort_keys=True).encode()).hexdigest()
    checksum = hashlib.sha256(
        json.dumps(normalized_rows, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()
    return DataBatch(
        connector_id=connector_id,
        columns=columns,
        rows=normalized_rows,
        row_count=len(normalized_rows),
        source_version=source_version,
        schema_fingerprint=schema_fingerprint,
        cursor=cursor,
        checksum=checksum,
        run_id=f"CONN-{uuid4()}",
        data_classification=data_classification,
        next_offset=next_offset,
    )

