from app.platform.connectors.base import Connector
from app.platform.connectors.capabilities import ConnectorCapabilities, IncrementalMode
from app.platform.connectors.contracts import (
    CancellationToken,
    CatalogItem,
    ColumnItem,
    ConnectionTest,
    DataBatch,
    HealthStatus,
    PageRequest,
    ProfileResult,
    RelationshipItem,
    SchemaItem,
    Selection,
    TableItem,
)
from app.platform.connectors.errors import ConnectorError, ConnectorErrorCode
from app.platform.connectors.security import CredentialProvider, validate_no_plaintext_credentials
from app.platform.connectors.utils import make_batch, normalized_type


class MockConnector(Connector):
    def __init__(self, config, credential_provider: CredentialProvider):
        del credential_provider
        validate_no_plaintext_credentials(config)
        self.config = config
        self.rows = [dict(row) for row in config.options.get("rows", [])]
        self.failure = config.options.get("failure")
        self._closed = False

    @property
    def capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities(
            catalogs=True,
            schemas=True,
            relationships=True,
            incremental_modes=(IncrementalMode.NONE, IncrementalMode.WATERMARK),
        )

    def _check(self, cancellation: CancellationToken | None = None) -> None:
        if cancellation:
            cancellation.raise_if_cancelled()
        if self._closed:
            raise ConnectorError(ConnectorErrorCode.SOURCE_UNAVAILABLE, "连接器已关闭")
        if self.failure:
            code = ConnectorErrorCode(str(self.failure))
            raise ConnectorError(code, "Mock 连接器受控失败")

    def _columns(self) -> tuple[ColumnItem, ...]:
        names = list(self.rows[0]) if self.rows else []
        return tuple(ColumnItem(
            name=name,
            normalized_type=normalized_type(next((row.get(name) for row in self.rows if row.get(name) is not None), None)),
            source_type="mock",
            nullable=any(row.get(name) is None for row in self.rows),
            ordinal=index,
        ) for index, name in enumerate(names, start=1))

    def test_connection(self, *, timeout_seconds: int = 5, cancellation: CancellationToken | None = None) -> ConnectionTest:
        del timeout_seconds
        self._check(cancellation)
        return ConnectionTest(status="ok", latency_ms=0, server={"driver": "mock"})

    def discover_catalogs(self, *, cancellation: CancellationToken | None = None) -> tuple[CatalogItem, ...]:
        self._check(cancellation)
        return (CatalogItem("mock"),)

    def discover_schemas(self, catalog: str | None = None, *, cancellation: CancellationToken | None = None) -> tuple[SchemaItem, ...]:
        del catalog
        self._check(cancellation)
        return (SchemaItem("default", "mock"),)

    def discover_tables(self, schema: str | None = None, *, cancellation: CancellationToken | None = None) -> tuple[TableItem, ...]:
        del schema
        self._check(cancellation)
        return (TableItem("records", "default", "mock"),)

    def discover_columns(self, selection: Selection, *, cancellation: CancellationToken | None = None) -> tuple[ColumnItem, ...]:
        del selection
        self._check(cancellation)
        return self._columns()

    def discover_relationships(self, selection: Selection, *, cancellation: CancellationToken | None = None) -> tuple[RelationshipItem, ...]:
        del selection
        self._check(cancellation)
        return ()

    def read_batch(self, selection: Selection, page: PageRequest = PageRequest(), *, cancellation: CancellationToken | None = None) -> DataBatch:
        del selection
        self._check(cancellation)
        rows = self.rows[page.offset:page.offset + page.limit]
        next_offset = page.offset + len(rows) if page.offset + len(rows) < len(self.rows) else None
        return make_batch(
            self.config.connector_id,
            self._columns(),
            rows,
            source_version="mock-v1",
            data_classification=str(self.config.options.get("data_classification", "simulated")),
            next_offset=next_offset,
        )

    def preview_data(self, selection: Selection, page: PageRequest = PageRequest(), *, cancellation: CancellationToken | None = None) -> DataBatch:
        return self.read_batch(selection, page, cancellation=cancellation)

    def profile_data(self, selection: Selection, page: PageRequest = PageRequest(), *, cancellation: CancellationToken | None = None) -> ProfileResult:
        batch = self.read_batch(selection, page, cancellation=cancellation)
        return ProfileResult(
            row_count=len(self.rows),
            sampled_rows=batch.row_count,
            null_counts={column.name: sum(row.get(column.name) is None for row in batch.rows) for column in batch.columns},
            distinct_counts={column.name: len({str(row.get(column.name)) for row in batch.rows}) for column in batch.columns},
        )

    def read_incremental(self, selection: Selection, cursor: str | None, page: PageRequest = PageRequest(), *, cancellation: CancellationToken | None = None) -> DataBatch:
        self._check(cancellation)
        if not selection.watermark_column:
            raise ConnectorError(ConnectorErrorCode.CONFIG_ERROR, "增量读取需要 watermark_column")
        filtered = [
            row for row in self.rows
            if cursor is None or str(row.get(selection.watermark_column, "")) > cursor
        ]
        rows = filtered[:page.limit]
        next_cursor = str(rows[-1][selection.watermark_column]) if rows else cursor
        return make_batch(
            self.config.connector_id,
            self._columns(),
            rows,
            source_version="mock-v1",
            data_classification=str(self.config.options.get("data_classification", "simulated")),
            cursor=next_cursor,
        )

    def health_check(self) -> HealthStatus:
        try:
            self._check()
            return HealthStatus(status="ok")
        except ConnectorError as exc:
            return HealthStatus(status="error", error_code=exc.code.value)

    def close(self) -> None:
        self._closed = True

