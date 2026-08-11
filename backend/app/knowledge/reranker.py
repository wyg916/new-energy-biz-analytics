from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from app.knowledge.indexer import cosine_similarity, decode_index, feature_hash_vector, tokenize
from app.models.knowledge import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
)

RRF_K = 60
# The deterministic feature-hash vector is lexical and collision-prone. It may
# fuse and rerank an FTS-supported candidate, but cannot establish evidence by
# itself. This keeps hash collisions from crossing the no-evidence boundary.
MIN_VECTOR_SIMILARITY = 0.30
_QUERY_FORM_TERMS = frozenset({
    "什么", "怎么", "如何", "多少", "是多", "是否", "能否", "为何",
    "为什", "怎样", "哪一", "哪些", "请问", "告诉", "解释", "说明",
})


@dataclass(frozen=True)
class RankedChunk:
    chunk: KnowledgeChunk
    version: KnowledgeDocumentVersion
    document: KnowledgeDocument
    score: float
    keyword_score: float = 0.0
    vector_score: float = 0.0
    rrf_score: float = 0.0


def keyword_terms(value: str) -> set[str]:
    # Question-form bigrams are not business evidence. Without this boundary,
    # an unrelated question such as "火星基地量子税率是多少" can match a chunk
    # solely because both texts contain "是多少".
    return set(tokenize(value)) - _QUERY_FORM_TERMS


def _bm25(query_tokens: list[str], rows: list[tuple]) -> dict[str, float]:
    indexed = [(row, decode_index(row[3])) for row in rows]
    valid = [(row, values) for row, values in indexed if values is not None]
    if not valid:
        return {}
    average_length = sum(values.token_count for _, values in valid) / len(valid)
    document_frequency = Counter()
    for _, values in valid:
        for term in set(query_tokens) & set(values.term_frequency):
            document_frequency[term] += 1
    scores: dict[str, float] = {}
    for row, values in valid:
        score = 0.0
        for term in query_tokens:
            frequency = values.term_frequency.get(term, 0)
            if not frequency:
                continue
            count = len(valid)
            df = document_frequency[term]
            inverse = math.log(1 + (count - df + 0.5) / (df + 0.5))
            denominator = frequency + 1.2 * (1 - 0.75 + 0.75 * values.token_count / max(1, average_length))
            score += inverse * (frequency * 2.2 / denominator)
        scores[row[0].chunk_id] = score
    maximum = max(scores.values(), default=0.0)
    return {key: value / maximum if maximum else 0.0 for key, value in scores.items()}


def _vector_scores(query_tokens: list[str], rows: list[tuple]) -> dict[str, float]:
    query_vector = feature_hash_vector(query_tokens)
    scores: dict[str, float] = {}
    for chunk, _, _, index in rows:
        values = decode_index(index)
        if values is not None:
            scores[chunk.chunk_id] = max(0.0, cosine_similarity(query_vector, values.vector))
    return scores


def rank_candidates(query: str, candidates: list[tuple], *, limit: int) -> list[RankedChunk]:
    query_tokens = [term for term in tokenize(query) if term not in _QUERY_FORM_TERMS]
    keyword = _bm25(query_tokens, candidates)
    vector = _vector_scores(query_tokens, candidates)
    stable_key = {
        row[0].chunk_id: f"{row[2].source_path}:{row[0].ordinal:08d}"
        for row in candidates
    }
    keyword_order = sorted(
        (key for key, score in keyword.items() if score > 0),
        key=lambda key: (-keyword[key], stable_key[key]),
    )
    vector_order = sorted(
        (
            key for key, score in vector.items()
            if score >= MIN_VECTOR_SIMILARITY and keyword.get(key, 0.0) > 0
        ),
        key=lambda key: (-vector[key], stable_key[key]),
    )
    keyword_rank = {chunk_id: rank for rank, chunk_id in enumerate(keyword_order, 1)}
    vector_rank = {chunk_id: rank for rank, chunk_id in enumerate(vector_order, 1)}
    by_id = {row[0].chunk_id: row for row in candidates}
    fused: list[RankedChunk] = []
    seen_hashes: set[str] = set()
    max_rrf = 2 / (RRF_K + 1)
    for chunk_id in sorted(set(keyword_rank) | set(vector_rank), key=stable_key.__getitem__):
        chunk, version, document, _ = by_id[chunk_id]
        if chunk.content_sha256 in seen_hashes:
            continue
        keyword_score = keyword.get(chunk_id, 0.0)
        vector_score = vector.get(chunk_id, 0.0)
        rrf = (
            (1 / (RRF_K + keyword_rank[chunk_id]) if chunk_id in keyword_rank else 0)
            + (1 / (RRF_K + vector_rank[chunk_id]) if chunk_id in vector_rank else 0)
        ) / max_rrf
        title_hit = bool(set(query_tokens) & set(tokenize(document.title)))
        section_hit = bool(set(query_tokens) & set(tokenize(chunk.section or "")))
        exact = query.strip().lower() in chunk.content.lower()
        reranked = min(
            1.0,
            0.42 * rrf + 0.32 * keyword_score + 0.18 * vector_score
            + (0.04 if title_hit else 0) + (0.025 if section_hit else 0)
            + (0.015 if exact else 0),
        )
        fused.append(RankedChunk(
            chunk=chunk, version=version, document=document,
            score=round(reranked, 6), keyword_score=round(keyword_score, 6),
            vector_score=round(vector_score, 6), rrf_score=round(rrf, 6),
        ))
        seen_hashes.add(chunk.content_sha256)
    fused.sort(key=lambda item: (
        -item.score, item.document.title, item.document.source_path, item.chunk.ordinal
    ))
    return fused[:limit]
