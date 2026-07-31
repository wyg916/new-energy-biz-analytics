import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.knowledge.approved_sources import APPROVED_SOURCE_PATHS
from app.knowledge.chunker import chunk_document
from app.knowledge.models import DocumentStatus, IngestionRequest
from app.knowledge.normalizer import normalize_content
from app.knowledge.parser import KnowledgeParseError, parse_document
from app.models.knowledge import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentAcl,
    KnowledgeDocumentVersion,
)
from app.platform.identity import IdentityContext


class KnowledgeIngestionError(RuntimeError):
    code = "KNOWLEDGE_INGESTION_ERROR"


class KnowledgeSourceDenied(KnowledgeIngestionError):
    code = "KNOWLEDGE_SOURCE_DENIED"


class KnowledgeIngestionService:
    def __init__(self, db: Session, identity: IdentityContext, repo_root: Path) -> None:
        self.db = db
        self.identity = identity
        self.repo_root = repo_root.resolve()

    def ingest(self, request: IngestionRequest) -> KnowledgeDocumentVersion:
        path = self._approved_source_path(request.source_path)
        document = self._get_or_create_document(request, path)
        version_number = int(self.db.scalar(
            select(func.coalesce(func.max(KnowledgeDocumentVersion.version), 0)).where(
                KnowledgeDocumentVersion.document_id == document.document_id
            )
        ) or 0) + 1
        version = KnowledgeDocumentVersion(
            document_version_id=f"kdv-{uuid4().hex}",
            document_id=document.document_id,
            version=version_number,
            status=DocumentStatus.UPLOADED,
            content_sha256="0" * 64,
            mime_type="application/octet-stream",
            size_bytes=0,
            raw_content="",
            normalized_content="",
            valid_from=request.valid_from,
            valid_to=request.valid_to,
            supersedes_version_id=None,
            failure_reason=None,
            created_by=self.identity.subject_id,
            created_at=datetime.now(UTC),
            published_at=None,
            retired_at=None,
        )
        self.db.add(version)
        self.db.flush()
        try:
            version.status = DocumentStatus.PARSING
            parsed = parse_document(path)
            version.raw_content = parsed.content
            version.mime_type = parsed.mime_type
            version.size_bytes = parsed.size_bytes
            version.content_sha256 = hashlib.sha256(parsed.content.encode("utf-8")).hexdigest()
            version.status = DocumentStatus.PARSED
            normalized = normalize_content(parsed.content)
            if not normalized:
                raise KnowledgeParseError("normalized document is empty")
            version.normalized_content = normalized
            drafts = chunk_document(normalized)
            if not drafts:
                raise KnowledgeParseError("document produced no chunks")
            for draft in drafts:
                self.db.add(KnowledgeChunk(
                    chunk_id=f"kch-{uuid4().hex}",
                    document_version_id=version.document_version_id,
                    ordinal=draft.ordinal,
                    section=draft.section,
                    page=None,
                    content=draft.content,
                    content_sha256=hashlib.sha256(draft.content.encode("utf-8")).hexdigest(),
                    token_estimate=max(1, len(draft.content) // 4),
                    created_at=datetime.now(UTC),
                ))
            version.status = DocumentStatus.CHUNKED
            self._add_acl(version.document_version_id, "role", request.roles)
            self._add_acl(version.document_version_id, "data_scope", request.data_scopes)
            version.status = DocumentStatus.INDEXING
            # P2A keyword index is represented by immutable chunks. Vector is explicitly pending.
            version.status = DocumentStatus.VALIDATING
            version.status = DocumentStatus.READY
            self.db.commit()
            return version
        except Exception as exc:
            self.db.rollback()
            failed = self.db.get(KnowledgeDocumentVersion, version.document_version_id)
            if failed is not None:
                failed.status = DocumentStatus.FAILED
                failed.failure_reason = type(exc).__name__[:512]
                self.db.commit()
            if isinstance(exc, KnowledgeIngestionError):
                raise
            raise KnowledgeIngestionError("document ingestion failed") from exc

    def _get_or_create_document(
        self,
        request: IngestionRequest,
        path: Path,
    ) -> KnowledgeDocument:
        if request.document_id:
            document = self.db.get(KnowledgeDocument, request.document_id)
            if (
                document is None
                or document.tenant_id != self.identity.tenant_id
                or document.workspace_id != self.identity.workspace_id
            ):
                raise KnowledgeSourceDenied("document is outside the caller scope")
            return document
        document = KnowledgeDocument(
            document_id=f"kdoc-{uuid4().hex}",
            tenant_id=self.identity.tenant_id,
            workspace_id=self.identity.workspace_id,
            scenario_id=request.scenario_id,
            knowledge_domain=request.knowledge_domain,
            title=request.title,
            source_path=path.relative_to(self.repo_root).as_posix(),
            source_kind="tracked_repository_document",
            created_by=self.identity.subject_id,
            created_at=datetime.now(UTC),
        )
        self.db.add(document)
        self.db.flush()
        return document

    def _approved_source_path(self, source_path: str) -> Path:
        candidate = (self.repo_root / source_path).resolve()
        if self.repo_root not in candidate.parents or not candidate.is_file():
            raise KnowledgeSourceDenied("knowledge source must be a repository file")
        relative = candidate.relative_to(self.repo_root).as_posix()
        if relative not in APPROVED_SOURCE_PATHS:
            raise KnowledgeSourceDenied("knowledge source is not in the reviewed tracked-source manifest")
        return candidate

    def _add_acl(self, version_id: str, principal_type: str, values: tuple[str, ...]) -> None:
        clean = sorted({value.strip() for value in values if value.strip()})
        if not clean:
            raise KnowledgeIngestionError(f"{principal_type} ACL cannot be empty")
        for value in clean:
            self.db.add(KnowledgeDocumentAcl(
                acl_id=f"kacl-{uuid4().hex}",
                document_version_id=version_id,
                principal_type=principal_type,
                principal_value=value,
            ))
