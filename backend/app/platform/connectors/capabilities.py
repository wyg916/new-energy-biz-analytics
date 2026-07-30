from dataclasses import dataclass
from enum import StrEnum


class IncrementalMode(StrEnum):
    NONE = "none"
    TIMESTAMP = "timestamp"
    WATERMARK = "watermark"
    CDC = "cdc"


@dataclass(frozen=True)
class ConnectorCapabilities:
    catalogs: bool = False
    schemas: bool = False
    tables: bool = True
    columns: bool = True
    relationships: bool = False
    preview: bool = True
    profile: bool = True
    batch: bool = True
    incremental_modes: tuple[IncrementalMode, ...] = (IncrementalMode.NONE,)
    cancellation: bool = True
    pagination: bool = True
    sampling: bool = True

    def as_dict(self) -> dict:
        return {
            "catalogs": self.catalogs,
            "schemas": self.schemas,
            "tables": self.tables,
            "columns": self.columns,
            "relationships": self.relationships,
            "preview": self.preview,
            "profile": self.profile,
            "batch": self.batch,
            "incremental_modes": [mode.value for mode in self.incremental_modes],
            "cancellation": self.cancellation,
            "pagination": self.pagination,
            "sampling": self.sampling,
        }

