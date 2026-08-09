from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.knowledge.security import prompt_injection_detected
from app.knowledge.indexer import EMBEDDING_MODEL, EMBEDDING_VERSION
from app.models.knowledge import (
    KnowledgeChunk,
    KnowledgeChunkIndex,
    KnowledgeDocumentVersion,
    KnowledgeGovernanceEvent,
)

AUTOMATED_GOVERNANCE_ROLES = frozenset({"system_reviewer", "rag_quality_agent"})
AUTOMATED_ACTIONS = frozenset({"METADATA_REVIEW", "INDEX_QUALITY_REVIEW", "INJECTION_SCAN"})


class KnowledgeGovernanceError(RuntimeError):
    code = "KNOWLEDGE_GOVERNANCE_ERROR"


class AutomatedKnowledgeGovernance:
    """Controlled review-only automation. It cannot publish, retire or rollback."""

    def __init__(self, db: Session, *, role: str) -> None:
        if role not in AUTOMATED_GOVERNANCE_ROLES:
            raise KnowledgeGovernanceError("automated governance role is not allowlisted")
        self.db = db
        self.role = role
        self.actor_id = f"system:{role}"

    def review(self, version_id: str, *, action: str, reason_code: str) -> KnowledgeGovernanceEvent:
        if action not in AUTOMATED_ACTIONS:
            raise KnowledgeGovernanceError("automated governance action is not allowlisted")
        version = self.db.get(KnowledgeDocumentVersion, version_id)
        if version is None:
            raise KnowledgeGovernanceError("knowledge version not found")
        chunks = list(self.db.scalars(select(KnowledgeChunk).where(
            KnowledgeChunk.document_version_id == version_id
        )))
        indexed_count = int(self.db.scalar(
            select(func.count()).select_from(KnowledgeChunkIndex).join(KnowledgeChunk).where(
                KnowledgeChunk.document_version_id == version_id,
                KnowledgeChunkIndex.embedding_model == EMBEDDING_MODEL,
                KnowledgeChunkIndex.embedding_version == EMBEDDING_VERSION,
                KnowledgeChunkIndex.content_sha256 == KnowledgeChunk.content_sha256,
            )
        ) or 0)
        rejected = sum(prompt_injection_detected(chunk.content) for chunk in chunks)
        before = {"status": str(version.status), "chunk_count": len(chunks)}
        after = {
            "indexed_chunk_count": indexed_count,
            "prompt_injection_chunk_count": rejected,
            "publication_changed": False,
        }
        decision = "PASS" if chunks and indexed_count == len(chunks) and not rejected else "REVIEW_REQUIRED"
        event = KnowledgeGovernanceEvent(
            audit_id=f"kgov-{uuid4().hex}",
            document_version_id=version_id,
            actor_id=self.actor_id,
            actor_type="SYSTEM",
            governance_role=self.role,
            action=action,
            reason_code=reason_code,
            decision=decision,
            before_json=json.dumps(before, ensure_ascii=False, sort_keys=True),
            after_json=json.dumps(after, ensure_ascii=False, sort_keys=True),
            created_at=datetime.now(UTC),
        )
        self.db.add(event)
        return event
