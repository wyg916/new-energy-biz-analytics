import json
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
        paragraph_start=item.chunk.paragraph_start,
        paragraph_end=item.chunk.paragraph_end,
        locator=_locator(item.chunk.locator_json, item.chunk.page, item.chunk.section),
        source=item.document.source_path,
        published_at=version.published_at,
        citation_text=item.chunk.content[:500],
        retrieval_score=item.score,
    )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _locator(raw: str, page: int | None, section: str | None) -> str:
    try:
        locator = json.loads(raw or "{}")
    except json.JSONDecodeError:
        locator = {}
    values = []
    if locator.get("page") or page:
        values.append(f"page:{locator.get('page') or page}")
    if locator.get("section") or section:
        values.append(f"section:{locator.get('section') or section}")
    start = locator.get("paragraph_start")
    end = locator.get("paragraph_end")
    if start:
        values.append(f"paragraph:{start}" if start == end else f"paragraph:{start}-{end}")
    return ";".join(values) or "document"
