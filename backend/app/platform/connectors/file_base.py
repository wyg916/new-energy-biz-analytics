from abc import abstractmethod
from pathlib import Path

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
from app.platform.connectors.security import CredentialProvider, resolve_controlled_path, validate_no_plaintext_credentials
from app.platform.connectors.utils import make_batch, normalized_type


class FileConnector(Connector):
    suffixes: set[str] = set()

    def __init__(self, config, credential_provider: CredentialProvider):
        del credential_provider
        validate_no_plaintext_credentials(config)
        self.config = config
        root = config.options.get("root_dir")
        locator = config.options.get("resource_locator")
        if not isinstance(root, str) or not isinstance(locator, str):
            raise ConnectorError(ConnectorErrorCode.CONFIG_ERROR, "文件连接器需要 root_dir 和 resource_locator")
        self.path = resolve_controlled_path(root, locator, self.suffixes)
        self.data_classification = str(config.options.get("data_classification", "unclassified"))
        self._closed = False

    @property
    def capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities(
            schemas=True,
            relationships=False,
            incremental_modes=(IncrementalMode.NONE,),
        )

    def _check(self, cancellation: CancellationToken | None = None) -> None:
        if self._closed:
            raise ConnectorError(ConnectorErrorCode.SOURCE_UNAVAILABLE, "连接器已关闭")
        if cancellation:
            cancellation.raise_if_cancelled()

    def test_connection(self, *, timeout_seconds: int = 5, cancellation: CancellationToken | None = None) -> ConnectionTest:
        del timeout_seconds
        self._check(cancellation)
        return ConnectionTest(status="ok", latency_ms=0, server={"file_name": self.path.name})

    def discover_catalogs(self, *, cancellation: CancellationToken | None = None) -> tuple[CatalogItem, ...]:
        self._check(cancellation)
        return ()

    def discover_schemas(self, catalog: str | None = None, *, cancellation: CancellationToken | None = None) -> tuple[SchemaItem, ...]:
        del catalog
        self._check(cancellation)
        return (SchemaItem(name="file"),)

    def discover_relationships(self, selection: Selection, *, cancellation: CancellationToken | None = None) -> tuple[RelationshipItem, ...]:
        del selection
        self._check(cancellation)
        return ()

    def preview_data(self, selection: Selection, page: PageRequest = PageRequest(), *, cancellation: CancellationToken | None = None) -> DataBatch:
        return self.read_batch(selection, page, cancellation=cancellation)

    def profile_data(self, selection: Selection, page: PageRequest = PageRequest(), *, cancellation: CancellationToken | None = None) -> ProfileResult:
        batch = self.read_batch(selection, page, cancellation=cancellation)
        null_counts = {
            column.name: sum(row.get(column.name) in (None, "") for row in batch.rows)
            for column in batch.columns
        }
        distinct_counts = {
            column.name: len({str(row.get(column.name)) for row in batch.rows})
            for column in batch.columns
        }
        return ProfileResult(
            row_count=self.total_rows(selection, cancellation=cancellation),
            sampled_rows=batch.row_count,
            null_counts=null_counts,
            distinct_counts=distinct_counts,
        )

    def read_incremental(self, selection: Selection, cursor: str | None, page: PageRequest = PageRequest(), *, cancellation: CancellationToken | None = None) -> DataBatch:
        del selection, cursor, page
        self._check(cancellation)
        raise ConnectorError(ConnectorErrorCode.UNSUPPORTED, "该文件连接器不支持增量读取")

    def health_check(self) -> HealthStatus:
        try:
            self._check()
            if not self.path.is_file():
                raise ConnectorError(ConnectorErrorCode.SOURCE_UNAVAILABLE, "数据文件不存在")
            return HealthStatus(status="ok")
        except ConnectorError as exc:
            return HealthStatus(status="error", error_code=exc.code.value)

    def close(self) -> None:
        self._closed = True

    def _columns_from_rows(self, headers: list[str], rows: list[dict]) -> tuple[ColumnItem, ...]:
        result = []
        for ordinal, name in enumerate(headers, start=1):
            source_value = next((row.get(name) for row in rows if row.get(name) not in (None, "")), None)
            inferred = normalized_type(source_value)
            result.append(ColumnItem(
                name=name,
                normalized_type=inferred,
                source_type=inferred,
                nullable=any(row.get(name) in (None, "") for row in rows),
                ordinal=ordinal,
            ))
        return tuple(result)

    def _batch(self, columns: tuple[ColumnItem, ...], rows: list[dict], page: PageRequest, total: int) -> DataBatch:
        next_offset = page.offset + len(rows) if page.offset + len(rows) < total else None
        source_version = f"{self.path.stat().st_mtime_ns}:{self.path.stat().st_size}"
        return make_batch(
            self.config.connector_id,
            columns,
            rows,
            source_version=source_version,
            data_classification=self.data_classification,
            next_offset=next_offset,
        )

    @abstractmethod
    def total_rows(self, selection: Selection, *, cancellation: CancellationToken | None = None) -> int:
        raise NotImplementedError

