from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Event
from typing import Any

from app.platform.connectors.errors import ConnectorError, ConnectorErrorCode


@dataclass(frozen=True)
class ConnectorConfig:
    connector_id: str
    connector_type: str
    options: dict[str, Any]
    credential_ref: str | None = None


@dataclass(frozen=True)
class PageRequest:
    limit: int = 100
    offset: int = 0
    sample: str = "head"

    def __post_init__(self) -> None:
        if self.limit < 1 or self.limit > 1000:
            raise ConnectorError(ConnectorErrorCode.CONFIG_ERROR, "分页 limit 必须在 1 到 1000 之间")
        if self.offset < 0:
            raise ConnectorError(ConnectorErrorCode.CONFIG_ERROR, "分页 offset 不能小于 0")
        if self.sample not in {"head", "deterministic"}:
            raise ConnectorError(ConnectorErrorCode.CONFIG_ERROR, "不支持的数据抽样方式")


@dataclass(frozen=True)
class Selection:
    catalog: str | None = None
    schema: str | None = None
    table: str | None = None
    columns: tuple[str, ...] = ()
    watermark_column: str | None = None


@dataclass(frozen=True)
class CatalogItem:
    name: str


@dataclass(frozen=True)
class SchemaItem:
    name: str
    catalog: str | None = None


@dataclass(frozen=True)
class TableItem:
    name: str
    schema: str | None = None
    catalog: str | None = None
    kind: str = "table"


@dataclass(frozen=True)
class ColumnItem:
    name: str
    normalized_type: str
    source_type: str
    nullable: bool = True
    ordinal: int = 0


@dataclass(frozen=True)
class RelationshipItem:
    name: str
    source_table: str
    source_columns: tuple[str, ...]
    target_table: str
    target_columns: tuple[str, ...]


@dataclass(frozen=True)
class ConnectionTest:
    status: str
    latency_ms: int
    server: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DataBatch:
    connector_id: str
    columns: tuple[ColumnItem, ...]
    rows: tuple[dict[str, Any], ...]
    row_count: int
    source_version: str
    schema_fingerprint: str
    cursor: str | None
    checksum: str
    run_id: str
    data_classification: str
    next_offset: int | None = None


@dataclass(frozen=True)
class ProfileResult:
    row_count: int
    sampled_rows: int
    null_counts: dict[str, int]
    distinct_counts: dict[str, int]


@dataclass(frozen=True)
class HealthStatus:
    status: str
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    error_code: str | None = None


class CancellationToken:
    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise ConnectorError(ConnectorErrorCode.CANCELLED, "连接器操作已取消")

