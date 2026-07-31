from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.knowledge.models import DocumentStatus
from app.models.knowledge import KnowledgeDocumentVersion, KnowledgePublicationEvent
from app.platform.identity import IdentityContext


class KnowledgePublicationError(RuntimeError):
    code = "KNOWLEDGE_PUBLICATION_ERROR"


class KnowledgePublicationService:
    def __init__(self, db: Session, identity: IdentityContext) -> None:
        self.db = db
        self.identity = identity

    def publish(self, version_id: str, *, reason: str | None = None) -> KnowledgeDocumentVersion:
        target = self._scoped_version(version_id)
        if target.status != DocumentStatus.READY:
            raise KnowledgePublicationError("only READY versions can be published")
        current = self.db.scalar(
            select(KnowledgeDocumentVersion).where(
                KnowledgeDocumentVersion.document_id == target.document_id,
                KnowledgeDocumentVersion.status == DocumentStatus.PUBLISHED,
            )
        )
        now = datetime.now(UTC)
        if current is not None:
            current.status = DocumentStatus.SUPERSEDED
            current.retired_at = now
            target.supersedes_version_id = current.document_version_id
        target.status = DocumentStatus.PUBLISHED
        target.published_at = now
        target.retired_at = None
        self._event(target, current, "PUBLISH", reason)
        self.db.commit()
        return target

    def retire(self, version_id: str, *, reason: str | None = None) -> KnowledgeDocumentVersion:
        target = self._scoped_version(version_id)
        if target.status != DocumentStatus.PUBLISHED:
            raise KnowledgePublicationError("only PUBLISHED versions can be retired")
        target.status = DocumentStatus.RETIRED
        target.retired_at = datetime.now(UTC)
        self._event(target, None, "RETIRE", reason)
        self.db.commit()
        return target

    def soft_delete(
        self,
        version_id: str,
        *,
        reason: str,
    ) -> KnowledgeDocumentVersion:
        """Governed logical deletion that preserves the immutable audit evidence."""

        target = self._scoped_version(version_id)
        if target.status not in {
            DocumentStatus.READY,
            DocumentStatus.PUBLISHED,
            DocumentStatus.SUPERSEDED,
            DocumentStatus.RETIRED,
            DocumentStatus.FAILED,
        }:
            raise KnowledgePublicationError("knowledge version cannot be deleted from its current state")
        target.status = DocumentStatus.RETIRED
        target.retired_at = datetime.now(UTC)
        self._event(target, None, "DELETE", reason)
        self.db.commit()
        return target

    def rollback(
        self,
        current_version_id: str,
        target_version_id: str,
        *,
        reason: str,
    ) -> KnowledgeDocumentVersion:
        current = self._scoped_version(current_version_id)
        target = self._scoped_version(target_version_id)
        if current.document_id != target.document_id:
            raise KnowledgePublicationError("rollback versions must belong to one document")
        if current.status != DocumentStatus.PUBLISHED:
            raise KnowledgePublicationError("rollback source must be PUBLISHED")
        if target.status != DocumentStatus.SUPERSEDED:
            raise KnowledgePublicationError("rollback target must be SUPERSEDED")
        now = datetime.now(UTC)
        current.status = DocumentStatus.SUPERSEDED
        current.retired_at = now
        target.status = DocumentStatus.PUBLISHED
        target.retired_at = None
        target.published_at = now
        self._event(target, current, "ROLLBACK", reason)
        self.db.commit()
        return target

    def _scoped_version(self, version_id: str) -> KnowledgeDocumentVersion:
        from app.models.knowledge import KnowledgeDocument

        target = self.db.scalar(
            select(KnowledgeDocumentVersion)
            .join(KnowledgeDocument)
            .where(
                KnowledgeDocumentVersion.document_version_id == version_id,
                KnowledgeDocument.tenant_id == self.identity.tenant_id,
                KnowledgeDocument.workspace_id == self.identity.workspace_id,
            )
        )
        if target is None:
            raise KnowledgePublicationError("knowledge version not found in caller scope")
        return target

    def _event(
        self,
        target: KnowledgeDocumentVersion,
        previous: KnowledgeDocumentVersion | None,
        action: str,
        reason: str | None,
    ) -> None:
        self.db.add(KnowledgePublicationEvent(
            publication_event_id=f"kpub-{uuid4().hex}",
            document_version_id=target.document_version_id,
            previous_version_id=previous.document_version_id if previous else None,
            action=action,
            actor_id=self.identity.subject_id,
            reason=reason,
            created_at=datetime.now(UTC),
        ))
