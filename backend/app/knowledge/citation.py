from datetime import UTC, datetime

from app.knowledge.models import Citation
from app.knowledge.reranker import RankedChunk


def citation_from_ranked(item: RankedChunk, *, at_time: datetime) -> Citation:
    version = item.version
    if version.status != "PUBLISHED" or version.published_at is None:
        raise ValueError("citation version is not published")
    effective_time = _utc(at_time)
    if version.valid_from and _utc(version.valid_from) > effective_time:
        raise ValueError("citation version is not yet valid")
    if version.valid_to and _utc(version.valid_to) <= effective_time:
        raise ValueError("citation version has expired")
    return Citation(
        document_id=item.document.document_id,
        document_version_id=version.document_version_id,
        chunk_id=item.chunk.chunk_id,
        title=item.document.title,
        page=item.chunk.page,
        section=item.chunk.section,
        source=item.document.source_path,
        published_at=version.published_at,
        citation_text=item.chunk.content[:500],
        retrieval_score=item.score,
    )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
