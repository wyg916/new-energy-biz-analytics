from dataclasses import dataclass

from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeDocumentVersion


@dataclass(frozen=True)
class RankedChunk:
    chunk: KnowledgeChunk
    version: KnowledgeDocumentVersion
    document: KnowledgeDocument
    score: float


def keyword_terms(value: str) -> set[str]:
    normalized = "".join(character.lower() if character.isalnum() else " " for character in value)
    words = {item for item in normalized.split() if len(item) >= 2}
    compact = "".join(character for character in value.lower() if character.isalnum())
    bigrams = {compact[index : index + 2] for index in range(max(0, len(compact) - 1))}
    return words | bigrams


def rank_candidates(query: str, candidates: list[tuple], *, limit: int) -> list[RankedChunk]:
    query_terms = keyword_terms(query)
    ranked: list[RankedChunk] = []
    seen_hashes: set[str] = set()
    for chunk, version, document in candidates:
        if chunk.content_sha256 in seen_hashes:
            continue
        content_terms = keyword_terms(f"{document.title} {chunk.section or ''} {chunk.content}")
        matches = query_terms & content_terms
        if not matches:
            continue
        overlap = len(matches) / max(1, len(query_terms))
        title_boost = 0.15 if query_terms & keyword_terms(document.title) else 0.0
        phrase_boost = 0.1 if query.lower() in chunk.content.lower() else 0.0
        score = min(1.0, overlap + title_boost + phrase_boost)
        seen_hashes.add(chunk.content_sha256)
        ranked.append(RankedChunk(chunk, version, document, round(score, 6)))
    ranked.sort(key=lambda item: (-item.score, item.document.title, item.chunk.ordinal))
    return ranked[:limit]
