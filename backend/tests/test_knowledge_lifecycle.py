import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.knowledge.ingestion import KnowledgeIngestionService, KnowledgeSourceDenied
from app.knowledge.models import (
    DocumentStatus,
    IngestionRequest,
    KnowledgeDomain,
    RetrievalIdentity,
)
from app.knowledge.publication import KnowledgePublicationService
from app.knowledge.retrieval import KnowledgeRetrievalService
from app.models.knowledge import (
    KnowledgeChunk,
    KnowledgeDocumentVersion,
    KnowledgePublicationEvent,
    KnowledgeRetrievalEvent,
)
from app.platform.identity import IdentityContext

_default_repo_root = Path(__file__).resolve().parents[2]
if not (_default_repo_root / "docs").is_dir():
    _default_repo_root = Path(get_settings().knowledge_source_root)
REPO_ROOT = Path(os.getenv("TEST_REPO_ROOT", _default_repo_root))
SOURCE = "docs/metric_dictionary_v0.1.md"


@pytest.fixture
def db_session():
    with SessionLocal() as session:
        yield session


def identity(
    *,
    subject: str = "user:1",
    role: str = "analyst_admin",
    workspace: str = "workspace-alpha",
) -> IdentityContext:
    return IdentityContext(
        subject_id=subject,
        tenant_id="tenant-alpha",
        org_id="org-alpha",
        workspace_id=workspace,
        roles=(role,),
        groups=(),
        data_scopes=("workspace:all",),
        auth_strength="test",
        issued_at=datetime.now(UTC),
        request_id="REQ-knowledge-test",
    )


def request(
    *,
    scenario: str = "charging_ops",
    document_id: str | None = None,
    roles: tuple[str, ...] = ("analyst_admin",),
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
) -> IngestionRequest:
    return IngestionRequest(
        source_path=SOURCE,
        title="指标字典 v0.1",
        scenario_id=scenario,
        knowledge_domain=KnowledgeDomain.METRIC_DEFINITION,
        roles=roles,
        data_scopes=("workspace:all",),
        valid_from=valid_from,
        valid_to=valid_to,
        document_id=document_id,
    )


def retrieval_identity(
    *,
    subject: str = "user:1",
    role: str = "analyst_admin",
    workspace: str = "workspace-alpha",
) -> RetrievalIdentity:
    return RetrievalIdentity(
        subject_id=subject,
        tenant_id="tenant-alpha",
        workspace_id=workspace,
        roles=(role,),
        data_scopes=("workspace:all",),
    )


def test_ingest_requires_tracked_repository_source(db_session) -> None:
    service = KnowledgeIngestionService(db_session, identity(), REPO_ROOT)

    with pytest.raises(KnowledgeSourceDenied):
        service.ingest(IngestionRequest(
            source_path="RAG企业知识库_知识体系与企业级开发实施指南_v1.0.docx",
            title="untracked",
            scenario_id="charging_ops",
            knowledge_domain=KnowledgeDomain.SYSTEM_HELP,
            roles=("analyst_admin",),
            data_scopes=("workspace:all",),
        ))


def test_lifecycle_publish_supersede_and_rollback(db_session) -> None:
    actor = identity()
    ingestion = KnowledgeIngestionService(db_session, actor, REPO_ROOT)
    publication = KnowledgePublicationService(db_session, actor)
    first = ingestion.ingest(request())
    assert first.status == DocumentStatus.READY
    assert db_session.scalar(select(KnowledgeChunk).limit(1)) is not None

    publication.publish(first.document_version_id, reason="initial approval")
    second = ingestion.ingest(request(document_id=first.document_id))
    publication.publish(second.document_version_id, reason="version update")
    db_session.refresh(first)
    assert first.status == DocumentStatus.SUPERSEDED
    assert second.status == DocumentStatus.PUBLISHED

    publication.rollback(
        second.document_version_id,
        first.document_version_id,
        reason="verified rollback",
    )
    db_session.refresh(first)
    db_session.refresh(second)
    assert first.status == DocumentStatus.PUBLISHED
    assert second.status == DocumentStatus.SUPERSEDED
    assert len(list(db_session.scalars(select(KnowledgePublicationEvent)))) == 3


def test_only_authorized_current_published_version_is_retrieved(db_session) -> None:
    actor = identity()
    version = KnowledgeIngestionService(db_session, actor, REPO_ROOT).ingest(request())
    service = KnowledgeRetrievalService(db_session)

    before_publish = service.retrieve(
        "充电收入 指标定义",
        retrieval_identity(),
        scenario_id="charging_ops",
        trace_id="trace-before-publish",
    )
    assert before_publish.citations == ()

    KnowledgePublicationService(db_session, actor).publish(version.document_version_id)
    allowed = service.retrieve(
        "充电收入 指标定义",
        retrieval_identity(),
        scenario_id="charging_ops",
        trace_id="trace-allowed",
    )
    denied_role = service.retrieve(
        "充电收入 指标定义",
        retrieval_identity(role="executive"),
        scenario_id="charging_ops",
        trace_id="trace-denied-role",
    )
    denied_scenario = service.retrieve(
        "充电收入 指标定义",
        retrieval_identity(),
        scenario_id="sales_ops",
        trace_id="trace-denied-scenario",
    )

    assert allowed.citations
    assert all(item.document_version_id == version.document_version_id for item in allowed.citations)
    assert denied_role.citations == ()
    assert denied_scenario.citations == ()
    assert allowed.vector_status == "VECTOR_DEFERRED_POST_P5"
    assert allowed.retrieval_mode == "keyword_full_text_only"


def test_validity_window_and_retirement_remove_document_from_retrieval(db_session) -> None:
    now = datetime.now(UTC)
    actor = identity()
    version = KnowledgeIngestionService(db_session, actor, REPO_ROOT).ingest(request(
        valid_from=now - timedelta(days=1),
        valid_to=now + timedelta(days=1),
    ))
    publication = KnowledgePublicationService(db_session, actor)
    publication.publish(version.document_version_id)
    service = KnowledgeRetrievalService(db_session)

    expired = service.retrieve(
        "充电收入",
        retrieval_identity(),
        scenario_id="charging_ops",
        trace_id="trace-expired",
        at_time=now + timedelta(days=2),
    )
    assert expired.citations == ()

    publication.retire(version.document_version_id, reason="end of validity")
    retired = service.retrieve(
        "充电收入",
        retrieval_identity(),
        scenario_id="charging_ops",
        trace_id="trace-retired",
    )
    assert retired.citations == ()
    assert len(list(db_session.scalars(select(KnowledgeRetrievalEvent)))) == 2
