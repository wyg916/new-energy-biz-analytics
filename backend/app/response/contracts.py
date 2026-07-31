from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ResponseProfileName(StrEnum):
    EXECUTIVE_BRIEF = "executive_brief"
    ANALYST_DETAILED = "analyst_detailed"
    OPERATION_ACTION = "operation_action"
    CONCISE_QUERY = "concise_query"


class KeyMetric(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metric_code: str
    metric_name: str
    value: int | float | str
    unit: str | None = None
    comparison: str | None = None
    source: str
    metric_version: str | None = None


class DataEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    engine: str
    scenario_id: str
    structured_result: dict[str, Any]
    key_metrics: tuple[KeyMetric, ...] = ()
    conclusion: str | None = None
    analysis: tuple[str, ...] = ()
    drivers: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    recommended_actions: tuple[str, ...] = ()
    data_source: str
    metric_definition: tuple[str, ...] = ()
    sql: str | None = None
    run_id: str


class CitationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    citation_id: str
    document_id: str
    document_version_id: str
    chunk_id: str
    title: str
    page: int | None = None
    section: str | None = None
    source: str
    published_at: str
    citation_text: str
    retrieval_score: float = Field(ge=0, le=1)


class EvidenceClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: str
    text: str = Field(min_length=1, max_length=1200)
    citation_ids: tuple[str, ...] = ()
    confidence: float = Field(ge=0, le=1)


class KnowledgeEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claims: tuple[EvidenceClaim, ...]
    citations: tuple[CitationEvidence, ...]
    retrieval_mode: str
    vector_status: str
    warnings: tuple[str, ...] = ()


class CompositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    question: str = Field(min_length=1, max_length=4000)
    profile: ResponseProfileName
    data_evidence: DataEvidence | None = None
    knowledge_evidence: KnowledgeEvidence | None = None
    trace_id: str = Field(min_length=8, max_length=96)
    run_id: str = Field(min_length=8, max_length=96)
    can_show_sql: bool = False
    data_classification: str = "simulated"


class FinalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    conclusion: str
    key_metrics: tuple[KeyMetric, ...]
    analysis: tuple[str, ...]
    drivers: tuple[str, ...]
    evidence: tuple[str, ...]
    risks: tuple[str, ...]
    recommended_actions: tuple[str, ...]
    data_source: tuple[str, ...]
    metric_definition: tuple[str, ...]
    citations: tuple[CitationEvidence, ...]
    warnings: tuple[str, ...]
    confidence: float
    trace_id: str
    run_id: str
    profile: ResponseProfileName
    sql: str | None
    refused: bool
    data_classification: str
