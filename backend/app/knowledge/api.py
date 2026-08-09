from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.model_gateway.runtime import runtime_model_status
from app.api.dependencies import current_user, require_roles
from app.core.config import get_settings
from app.core.database import get_db
from app.knowledge.approved_sources import APPROVED_SOURCE_PATHS
from app.knowledge.ingestion import (
    KnowledgeIngestionError,
    KnowledgeIngestionService,
    KnowledgeSourceDenied,
)
from app.knowledge.models import (
    IngestionRequest,
    KnowledgeDomain,
    RetrievalIdentity,
)
from app.knowledge.publication import (
    KnowledgePublicationError,
    KnowledgePublicationService,
)
from app.knowledge.retrieval import KnowledgeRetrievalService
from app.knowledge.indexer import EMBEDDING_MODEL, EMBEDDING_VERSION, VECTOR_STATUS
from app.models.auth import User
from app.models.knowledge import (
    KnowledgeChunk,
    KnowledgeChunkIndex,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
)
from app.platform.identity import IdentityContextFactory
from app.governance.authorization import AuthorizationDenied, AuthorizationService, request_context

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _require(
    db: Session,
    user: User,
    action: str,
    *,
    resource_id: str | None = None,
    scenario_id: str | None = None,
) -> None:
    identity = IdentityContextFactory.from_user(user)
    try:
        AuthorizationService(db, identity).require(request_context(
            identity,
            action=action,
            resource_type="rag_document",
            resource_id=resource_id,
            scenario_id=scenario_id,
            environment=get_settings().app_env,
        ))
    except AuthorizationDenied as exc:
        raise HTTPException(403, detail={"code": exc.code, "message": str(exc)}) from exc


class IngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_path: str = Field(max_length=1024)
    title: str = Field(min_length=2, max_length=256)
    scenario_id: str = Field(pattern=r"^(charging_ops|sales_ops)$")
    knowledge_domain: KnowledgeDomain
    roles: tuple[str, ...] = Field(min_length=1)
    data_scopes: tuple[str, ...] = ("workspace:all",)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    document_id: str | None = Field(default=None, max_length=64)


class PublishRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class RollbackRequest(BaseModel):
    target_version_id: str = Field(min_length=8, max_length=64)
    reason: str = Field(min_length=3, max_length=500)


class RetrievalTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=1000)
    scenario_id: str = Field(pattern=r"^(charging_ops|sales_ops)$")
    limit: int = Field(default=5, ge=1, le=10)
    trace_id: str = Field(min_length=8, max_length=96)
    run_id: str | None = Field(default=None, max_length=96)


def _http_error(exc: Exception) -> HTTPException:
    code = getattr(exc, "code", type(exc).__name__.upper())
    status_code = 403 if isinstance(exc, KnowledgeSourceDenied) else 409
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": str(exc)},
    )


@router.get("/runtime")
def runtime(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    settings = get_settings()
    identity = IdentityContextFactory.from_user(user)
    published_chunk_count = int(db.scalar(
        select(func.count()).select_from(KnowledgeChunk)
        .join(KnowledgeDocumentVersion)
        .join(KnowledgeDocument)
        .where(
            KnowledgeDocumentVersion.status == "PUBLISHED",
            KnowledgeDocument.tenant_id == identity.tenant_id,
            KnowledgeDocument.workspace_id == identity.workspace_id,
            KnowledgeChunkIndex.embedding_model == EMBEDDING_MODEL,
            KnowledgeChunkIndex.embedding_version == EMBEDDING_VERSION,
            KnowledgeChunkIndex.content_sha256 == KnowledgeChunk.content_sha256,
        )
    ) or 0)
    indexed_chunk_count = int(db.scalar(
        select(func.count()).select_from(KnowledgeChunkIndex)
        .join(KnowledgeChunk)
        .join(KnowledgeDocumentVersion)
        .join(KnowledgeDocument)
        .where(
            KnowledgeDocumentVersion.status == "PUBLISHED",
            KnowledgeDocument.tenant_id == identity.tenant_id,
            KnowledgeDocument.workspace_id == identity.workspace_id,
        )
    ) or 0)
    index_ready = indexed_chunk_count == published_chunk_count
    return {
        "knowledge_service": "READY" if index_ready else "INDEX_BACKFILL_REQUIRED",
        "retrieval_mode": (
            "hybrid_bm25_vector_rrf_rerank"
            if index_ready else "hybrid_partial_index_fail_closed"
        ),
        "keyword_index": "equivalent_bm25_v1",
        "vector_status": VECTOR_STATUS if index_ready else "INDEX_BACKFILL_REQUIRED",
        "embedding_model": EMBEDDING_MODEL,
        "pgvector_claimed": False,
        "published_chunk_count": published_chunk_count,
        "indexed_chunk_count": indexed_chunk_count,
        "sqlbot_runtime": (
            "NOT_INCLUDED_IN_THIS_RELEASE"
            if not settings.sqlbot_included_in_v4_release
            else "READY" if settings.sqlbot_runtime_verified else "RUNTIME_PENDING"
        ),
        "model_gateway": runtime_model_status(),
        "data_classification": "simulated",
    }


@router.get("/source-catalog")
def source_catalog(_: User = Depends(require_roles("analyst_admin"))) -> dict:
    return {
        "sources": sorted(APPROVED_SOURCE_PATHS),
        "policy": "explicit_reviewed_tracked_sources_only",
        "automatic_workspace_scan": False,
    }


@router.get("/documents")
def documents(
    scenario_id: str | None = Query(default=None, pattern=r"^(charging_ops|sales_ops)$"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    _require(db, user, "rag.document.view", scenario_id=scenario_id)
    identity = IdentityContextFactory.from_user(user)
    query = (
        select(KnowledgeDocument, KnowledgeDocumentVersion)
        .join(KnowledgeDocumentVersion)
        .where(
            KnowledgeDocument.tenant_id == identity.tenant_id,
            KnowledgeDocument.workspace_id == identity.workspace_id,
        )
        .order_by(KnowledgeDocument.created_at.desc(), KnowledgeDocumentVersion.version.desc())
    )
    if scenario_id:
        query = query.where(KnowledgeDocument.scenario_id == scenario_id)
    rows = db.execute(query).all()
    return {
        "documents": [{
            "document_id": document.document_id,
            "document_version_id": version.document_version_id,
            "version": version.version,
            "title": document.title,
            "scenario_id": document.scenario_id,
            "knowledge_domain": document.knowledge_domain,
            "source": document.source_path,
            "status": version.status,
            "content_sha256": version.content_sha256,
            "valid_from": version.valid_from,
            "valid_to": version.valid_to,
            "published_at": version.published_at,
            "chunk_count": db.scalar(select(func.count()).select_from(KnowledgeChunk).where(
                KnowledgeChunk.document_version_id == version.document_version_id
            )),
        } for document, version in rows],
        "data_classification": "simulated",
    }


@router.post("/documents/ingest")
def ingest(
    payload: IngestRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("analyst_admin")),
) -> dict:
    _require(db, user, "release.review", resource_id=payload.document_id, scenario_id=payload.scenario_id)
    identity = IdentityContextFactory.from_user(user)
    try:
        version = KnowledgeIngestionService(
            db,
            identity,
            Path(get_settings().knowledge_source_root),
        ).ingest(IngestionRequest(**payload.model_dump()))
    except KnowledgeIngestionError as exc:
        raise _http_error(exc) from exc
    return {
        "document_id": version.document_id,
        "document_version_id": version.document_version_id,
        "version": version.version,
        "status": version.status,
        "content_sha256": version.content_sha256,
    }


@router.post("/versions/{version_id}/publish")
def publish(
    version_id: str,
    payload: PublishRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("analyst_admin")),
) -> dict:
    _require(db, user, "release.activate", resource_id=version_id)
    try:
        version = KnowledgePublicationService(
            db,
            IdentityContextFactory.from_user(user),
        ).publish(version_id, reason=payload.reason)
    except KnowledgePublicationError as exc:
        raise _http_error(exc) from exc
    return {"document_version_id": version.document_version_id, "status": version.status}


@router.post("/versions/{version_id}/retire")
def retire(
    version_id: str,
    payload: PublishRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("analyst_admin")),
) -> dict:
    _require(db, user, "release.activate", resource_id=version_id)
    try:
        version = KnowledgePublicationService(
            db,
            IdentityContextFactory.from_user(user),
        ).retire(version_id, reason=payload.reason)
    except KnowledgePublicationError as exc:
        raise _http_error(exc) from exc
    return {"document_version_id": version.document_version_id, "status": version.status}


@router.post("/versions/{version_id}/delete")
def soft_delete(
    version_id: str,
    payload: PublishRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("analyst_admin")),
) -> dict:
    _require(db, user, "release.activate", resource_id=version_id)
    try:
        version = KnowledgePublicationService(
            db,
            IdentityContextFactory.from_user(user),
        ).soft_delete(
            version_id,
            reason=payload.reason or "governed logical deletion",
        )
    except KnowledgePublicationError as exc:
        raise _http_error(exc) from exc
    return {
        "document_version_id": version.document_version_id,
        "status": version.status,
        "deletion_mode": "logical_audit_preserving",
    }


@router.post("/versions/{version_id}/rollback")
def rollback(
    version_id: str,
    payload: RollbackRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("analyst_admin")),
) -> dict:
    _require(db, user, "release.rollback", resource_id=version_id)
    try:
        version = KnowledgePublicationService(
            db,
            IdentityContextFactory.from_user(user),
        ).rollback(version_id, payload.target_version_id, reason=payload.reason)
    except KnowledgePublicationError as exc:
        raise _http_error(exc) from exc
    return {"document_version_id": version.document_version_id, "status": version.status}


@router.post("/retrieval/test")
def retrieval_test(
    payload: RetrievalTestRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    _require(db, user, "rag.document.view", scenario_id=payload.scenario_id)
    identity = IdentityContextFactory.from_user(user)
    result = KnowledgeRetrievalService(db).retrieve(
        payload.query,
        RetrievalIdentity(
            subject_id=identity.subject_id,
            tenant_id=identity.tenant_id,
            workspace_id=identity.workspace_id,
            roles=identity.roles,
            data_scopes=identity.data_scopes,
        ),
        scenario_id=payload.scenario_id,
        trace_id=payload.trace_id,
        run_id=payload.run_id,
        limit=payload.limit,
    )
    return {
        "retrieval_mode": result.retrieval_mode,
        "vector_status": result.vector_status,
        "citations": [item.__dict__ for item in result.citations],
        "warnings": result.warnings,
        "rewritten_query": result.rewritten_query,
        "refusal_reason": result.refusal_reason,
        "answer_guard_status": result.answer_guard_status,
        "trace_id": result.trace_id,
        "run_id": result.run_id,
    }
