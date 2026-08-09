"""Backfill/rebuild the approved equivalent BM25/vector index with audit evidence."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, func, select

from app.core.database import SessionLocal
from app.knowledge.governance import AutomatedKnowledgeGovernance
from app.knowledge.indexer import EMBEDDING_MODEL, EMBEDDING_VERSION, index_for_chunk
from app.models.knowledge import (
    KnowledgeChunk,
    KnowledgeChunkIndex,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
)


def rebuild() -> dict:
    with SessionLocal() as db:
        rows = list(db.execute(
            select(KnowledgeChunk, KnowledgeDocumentVersion, KnowledgeDocument)
            .select_from(KnowledgeChunk)
            .join(
                KnowledgeDocumentVersion,
                KnowledgeChunk.document_version_id
                == KnowledgeDocumentVersion.document_version_id,
            )
            .join(
                KnowledgeDocument,
                KnowledgeDocumentVersion.document_id == KnowledgeDocument.document_id,
            )
        ).all())
        version_ids = sorted({version.document_version_id for _, version, _ in rows})
        db.execute(delete(KnowledgeChunkIndex).where(
            KnowledgeChunkIndex.embedding_model == EMBEDDING_MODEL,
            KnowledgeChunkIndex.embedding_version == EMBEDDING_VERSION,
        ))
        for chunk, _, document in rows:
            db.add(index_for_chunk(chunk, title=document.title))
        db.flush()
        reviewer = AutomatedKnowledgeGovernance(db, role="rag_quality_agent")
        decisions = []
        for version_id in version_ids:
            event = reviewer.review(
                version_id,
                action="INDEX_QUALITY_REVIEW",
                reason_code="CONTROLLED_INDEX_REBUILD",
            )
            decisions.append(event.decision)
        db.commit()
        vector_count = int(db.scalar(
            select(func.count()).select_from(KnowledgeChunkIndex).where(
                KnowledgeChunkIndex.embedding_model == EMBEDDING_MODEL,
                KnowledgeChunkIndex.embedding_version == EMBEDDING_VERSION,
            )
        ) or 0)
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "embedding_model": EMBEDDING_MODEL,
            "embedding_version": EMBEDDING_VERSION,
            "chunk_count": len(rows),
            "vector_count": vector_count,
            "reviewed_version_count": len(version_ids),
            "system_actor_type": "SYSTEM",
            "governance_role": "rag_quality_agent",
            "index_rebuild_passed": len(rows) == vector_count,
            "quality_reviews_all_passed": all(value == "PASS" for value in decisions),
            "review_required_count": sum(value == "REVIEW_REQUIRED" for value in decisions),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = rebuild()
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if result["index_rebuild_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
