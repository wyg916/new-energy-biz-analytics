from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class KnowledgeDomain(StrEnum):
    METRIC_DEFINITION = "metric_definition"
    DATA_DICTIONARY = "data_dictionary"
    BUSINESS_RULE = "business_rule"
    ANALYSIS_METHOD = "analysis_method"
    SCENARIO_GUIDE = "scenario_guide"
    SECURITY_RULE = "security_rule"
    SYSTEM_HELP = "system_help"


class DocumentStatus(StrEnum):
    UPLOADED = "UPLOADED"
    PARSING = "PARSING"
    PARSED = "PARSED"
    CHUNKED = "CHUNKED"
    INDEXING = "INDEXING"
    VALIDATING = "VALIDATING"
    READY = "READY"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class IngestionRequest:
    source_path: str
    title: str
    scenario_id: str
    knowledge_domain: KnowledgeDomain
    roles: tuple[str, ...]
    data_scopes: tuple[str, ...]
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    document_id: str | None = None


@dataclass(frozen=True)
class RetrievalIdentity:
    subject_id: str
    tenant_id: str
    workspace_id: str
    roles: tuple[str, ...]
    data_scopes: tuple[str, ...]


@dataclass(frozen=True)
class Citation:
    document_id: str
    document_version_id: str
    chunk_id: str
    title: str
    page: int | None
    section: str | None
    paragraph_start: int | None
    paragraph_end: int | None
    locator: str
    source: str
    published_at: datetime
    citation_text: str
    retrieval_score: float


@dataclass(frozen=True)
class RetrievalResult:
    query: str
    citations: tuple[Citation, ...]
    retrieval_mode: str
    vector_status: str
    trace_id: str
    run_id: str | None
    warnings: tuple[str, ...]
    rewritten_query: str = ""
    context: str = ""
    refusal_reason: str | None = None
    answer_guard_status: str = "PASSED"
