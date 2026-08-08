"""Deterministic, database-persisted keyword and vector index primitives.

The vector is an explicitly named equivalent capability, not pgvector and not a
neural embedding. It uses stable multilingual feature hashing so cold starts,
rebuilds and rollback tests need no external model or credential.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from uuid import uuid4

from app.models.knowledge import KnowledgeChunk, KnowledgeChunkIndex

EMBEDDING_MODEL = "deterministic_multilingual_feature_hash_v1"
EMBEDDING_VERSION = "1.0.0"
EMBEDDING_DIMENSIONS = 256
VECTOR_STATUS = "EQUIVALENT_VECTOR_READY"
KEYWORD_INDEX = "equivalent_bm25_v1"

_LATIN_WORD = re.compile(r"[a-zA-Z][a-zA-Z0-9_.:-]*")
_CJK_RUN = re.compile(r"[\u3400-\u9fff]+")


def tokenize(value: str) -> list[str]:
    lowered = value.lower()
    tokens = [item for item in _LATIN_WORD.findall(lowered) if len(item) >= 2]
    for run in _CJK_RUN.findall(lowered):
        # CJK unigrams create unsafe false positives for unrelated questions
        # (for example, one shared character such as "率"). Bigrams retain
        # deterministic Chinese recall without broadening the evidence boundary.
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[index:index + 2] for index in range(len(run) - 1))
    return tokens


def feature_hash_vector(tokens: list[str], *, dimensions: int = EMBEDDING_DIMENSIONS) -> list[float]:
    vector = [0.0] * dimensions
    counts = Counter(tokens)
    for term, count in counts.items():
        digest = hashlib.blake2b(term.encode("utf-8"), digest_size=16).digest()
        index = int.from_bytes(digest[:8], "big") % dimensions
        sign = 1.0 if digest[8] & 1 else -1.0
        vector[index] += sign * (1.0 + math.log(count))
    norm = math.sqrt(sum(value * value for value in vector))
    if norm:
        return [round(value / norm, 8) for value in vector]
    return vector


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)


def index_for_chunk(chunk: KnowledgeChunk, *, title: str) -> KnowledgeChunkIndex:
    index_text = f"{title}\n{chunk.section or ''}\n{chunk.content}"
    tokens = tokenize(index_text)
    vector = feature_hash_vector(tokens)
    return KnowledgeChunkIndex(
        chunk_index_id=f"kcix-{uuid4().hex}",
        chunk_id=chunk.chunk_id,
        embedding_model=EMBEDDING_MODEL,
        embedding_version=EMBEDDING_VERSION,
        dimensions=EMBEDDING_DIMENSIONS,
        vector_json=json.dumps(vector, separators=(",", ":")),
        vector_norm=round(math.sqrt(sum(value * value for value in vector)), 8),
        term_frequency_json=json.dumps(Counter(tokens), ensure_ascii=False, sort_keys=True),
        token_count=len(tokens),
        content_sha256=chunk.content_sha256,
    )


@dataclass(frozen=True)
class IndexedValues:
    vector: list[float]
    term_frequency: Counter[str]
    token_count: int


def decode_index(index: KnowledgeChunkIndex | None) -> IndexedValues | None:
    if index is None or index.embedding_model != EMBEDDING_MODEL:
        return None
    try:
        vector = [float(value) for value in json.loads(index.vector_json)]
        frequency = Counter({
            str(term): int(count)
            for term, count in json.loads(index.term_frequency_json).items()
        })
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if len(vector) != EMBEDDING_DIMENSIONS or index.dimensions != EMBEDDING_DIMENSIONS:
        return None
    return IndexedValues(vector, frequency, index.token_count)
