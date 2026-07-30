from abc import ABC, abstractmethod

from app.platform.connectors.capabilities import ConnectorCapabilities
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


class Connector(ABC):
    @property
    @abstractmethod
    def capabilities(self) -> ConnectorCapabilities:
        raise NotImplementedError

    @abstractmethod
    def test_connection(self, *, timeout_seconds: int = 5, cancellation: CancellationToken | None = None) -> ConnectionTest:
        raise NotImplementedError

    @abstractmethod
    def discover_catalogs(self, *, cancellation: CancellationToken | None = None) -> tuple[CatalogItem, ...]:
        raise NotImplementedError

    @abstractmethod
    def discover_schemas(self, catalog: str | None = None, *, cancellation: CancellationToken | None = None) -> tuple[SchemaItem, ...]:
        raise NotImplementedError

    @abstractmethod
    def discover_tables(self, schema: str | None = None, *, cancellation: CancellationToken | None = None) -> tuple[TableItem, ...]:
        raise NotImplementedError

    @abstractmethod
    def discover_columns(self, selection: Selection, *, cancellation: CancellationToken | None = None) -> tuple[ColumnItem, ...]:
        raise NotImplementedError

    @abstractmethod
    def discover_relationships(self, selection: Selection, *, cancellation: CancellationToken | None = None) -> tuple[RelationshipItem, ...]:
        raise NotImplementedError

    @abstractmethod
    def preview_data(self, selection: Selection, page: PageRequest = PageRequest(), *, cancellation: CancellationToken | None = None) -> DataBatch:
        raise NotImplementedError

    @abstractmethod
    def profile_data(self, selection: Selection, page: PageRequest = PageRequest(), *, cancellation: CancellationToken | None = None) -> ProfileResult:
        raise NotImplementedError

    @abstractmethod
    def read_batch(self, selection: Selection, page: PageRequest = PageRequest(), *, cancellation: CancellationToken | None = None) -> DataBatch:
        raise NotImplementedError

    @abstractmethod
    def read_incremental(self, selection: Selection, cursor: str | None, page: PageRequest = PageRequest(), *, cancellation: CancellationToken | None = None) -> DataBatch:
        raise NotImplementedError

    @abstractmethod
    def health_check(self) -> HealthStatus:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

