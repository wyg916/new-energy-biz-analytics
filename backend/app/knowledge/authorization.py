from datetime import datetime

from sqlalchemy import and_, exists, or_, select

from app.knowledge.models import RetrievalIdentity
from app.knowledge.indexer import EMBEDDING_MODEL, EMBEDDING_VERSION
from app.models.knowledge import (
    KnowledgeChunk,
    KnowledgeChunkIndex,
    KnowledgeDocument,
    KnowledgeDocumentAcl,
    KnowledgeDocumentVersion,
)


def authorized_candidate_query(
    identity: RetrievalIdentity,
    *,
    scenario_id: str,
    at_time: datetime,
):
    role_values = tuple(set(identity.roles) | {"*"})
    scope_values = tuple(set(identity.data_scopes) | {"*"})
    role_acl = (
        select(KnowledgeDocumentAcl.acl_id)
        .where(
            KnowledgeDocumentAcl.document_version_id
            == KnowledgeDocumentVersion.document_version_id,
            KnowledgeDocumentAcl.principal_type == "role",
            KnowledgeDocumentAcl.principal_value.in_(role_values),
        )
        .exists()
    )
    scope_acl = (
        select(KnowledgeDocumentAcl.acl_id)
        .where(
            KnowledgeDocumentAcl.document_version_id
            == KnowledgeDocumentVersion.document_version_id,
            KnowledgeDocumentAcl.principal_type == "data_scope",
            KnowledgeDocumentAcl.principal_value.in_(scope_values),
        )
        .exists()
    )
    return (
        select(KnowledgeChunk, KnowledgeDocumentVersion, KnowledgeDocument, KnowledgeChunkIndex)
        .join(
            KnowledgeDocumentVersion,
            KnowledgeChunk.document_version_id
            == KnowledgeDocumentVersion.document_version_id,
        )
        .join(
            KnowledgeDocument,
            KnowledgeDocumentVersion.document_id == KnowledgeDocument.document_id,
        )
        .outerjoin(
            KnowledgeChunkIndex,
            and_(
                KnowledgeChunkIndex.chunk_id == KnowledgeChunk.chunk_id,
                KnowledgeChunkIndex.embedding_model == EMBEDDING_MODEL,
                KnowledgeChunkIndex.embedding_version == EMBEDDING_VERSION,
            ),
        )
        .where(
            KnowledgeDocument.tenant_id == identity.tenant_id,
            KnowledgeDocument.workspace_id == identity.workspace_id,
            KnowledgeDocument.scenario_id == scenario_id,
            KnowledgeDocumentVersion.status == "PUBLISHED",
            or_(
                KnowledgeDocumentVersion.valid_from.is_(None),
                KnowledgeDocumentVersion.valid_from <= at_time,
            ),
            or_(
                KnowledgeDocumentVersion.valid_to.is_(None),
                KnowledgeDocumentVersion.valid_to > at_time,
            ),
            role_acl,
            scope_acl,
        )
        .limit(500)
    )
