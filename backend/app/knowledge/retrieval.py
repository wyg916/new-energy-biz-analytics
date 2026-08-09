from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.knowledge.authorization import authorized_candidate_query
from app.knowledge.citation import citation_from_ranked
from app.knowledge.context import build_context
from app.knowledge.indexer import EMBEDDING_MODEL, KEYWORD_INDEX, VECTOR_STATUS, decode_index
from app.knowledge.models import RetrievalIdentity, RetrievalResult
from app.knowledge.query_rewrite import rewrite_query
from app.knowledge.reranker import RRF_K, rank_candidates
from app.knowledge.security import prompt_injection_detected
from app.models.knowledge import KnowledgeRetrievalEvent

RETRIEVAL_MODE = "hybrid_bm25_vector_rrf_rerank"


class KnowledgeRetrievalService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def retrieve(
        self,
        query: str,
        identity: RetrievalIdentity,
        *,
        scenario_id: str,
        trace_id: str,
        run_id: str | None = None,
        at_time: datetime | None = None,
        limit: int = 5,
    ) -> RetrievalResult:
        if not query.strip():
            raise ValueError("retrieval query cannot be empty")
        if limit < 1 or limit > 10:
            raise ValueError("retrieval limit must be between 1 and 10")
        started = time.perf_counter()
        now = at_time or datetime.now(UTC)
        rewrite = rewrite_query(query)
        if rewrite.rejected:
            result = self._empty_result(
                query=query, rewritten_query="", trace_id=trace_id, run_id=run_id,
                refusal_reason=rewrite.reason or "QUERY_REJECTED",
                warnings=("查询疑似包含 Prompt Injection，已在检索前拒绝。",),
            )
            self._audit(result, identity, scenario_id, started, 0, 0, 0)
            return result

        # Tenant/workspace/scenario/version/validity/role/data-scope predicates are
        # evaluated by SQL before any chunk content is materialized.
        candidates = list(self.db.execute(
            authorized_candidate_query(identity, scenario_id=scenario_id, at_time=now)
        ).all())
        safe_candidates = [item for item in candidates if not prompt_injection_detected(item[0].content)]
        injection_rejections = len(candidates) - len(safe_candidates)
        indexed_candidates = [
            item for item in safe_candidates
            if decode_index(item[3]) is not None
            and item[3].content_sha256 == item[0].content_sha256
        ]
        missing_indexes = len(safe_candidates) - len(indexed_candidates)
        ranked = rank_candidates(rewrite.rewritten, indexed_candidates, limit=limit)
        citations = tuple(citation_from_ranked(item, at_time=now) for item in ranked)
        context = build_context(citations)
        warnings: list[str] = [
            "混合检索使用数据库持久化 BM25 等价索引与确定性特征哈希向量；该向量不是 pgvector 或神经 embedding。"
        ]
        if rewrite.expansions:
            warnings.append("Query Rewrite 仅使用已审计同义词表，不调用模型。")
        if injection_rejections:
            warnings.append(f"已隔离 {injection_rejections} 个疑似 Prompt Injection 证据块。")
        if missing_indexes:
            warnings.append(f"{missing_indexes} 个授权证据块缺少当前索引，已 fail-closed 排除。")
        if context.truncated:
            warnings.append("Context Build 已按字符预算截断。")
        refusal_reason = None if citations else "NO_PUBLISHED_EVIDENCE"
        runtime_mode = RETRIEVAL_MODE if not missing_indexes else "hybrid_partial_index_fail_closed"
        runtime_vector_status = VECTOR_STATUS if not missing_indexes else "INDEX_BACKFILL_REQUIRED"
        result = RetrievalResult(
            query=query,
            citations=citations,
            retrieval_mode=runtime_mode,
            vector_status=runtime_vector_status,
            trace_id=trace_id,
            run_id=run_id,
            warnings=tuple(warnings),
            rewritten_query=rewrite.rewritten,
            context=context.text,
            refusal_reason=refusal_reason,
            answer_guard_status="PASSED" if citations else "REFUSED_NO_EVIDENCE",
        )
        self._audit(
            result, identity, scenario_id, started,
            keyword_candidates=len(indexed_candidates),
            vector_candidates=len(indexed_candidates),
            injection_rejections=injection_rejections,
        )
        return result

    def _empty_result(
        self,
        *,
        query: str,
        rewritten_query: str,
        trace_id: str,
        run_id: str | None,
        refusal_reason: str,
        warnings: tuple[str, ...],
    ) -> RetrievalResult:
        return RetrievalResult(
            query=query, citations=(), retrieval_mode=RETRIEVAL_MODE,
            vector_status=VECTOR_STATUS, trace_id=trace_id, run_id=run_id,
            warnings=warnings, rewritten_query=rewritten_query, context="",
            refusal_reason=refusal_reason, answer_guard_status="REFUSED",
        )

    def _audit(
        self,
        result: RetrievalResult,
        identity: RetrievalIdentity,
        scenario_id: str,
        started: float,
        keyword_candidates: int,
        vector_candidates: int,
        injection_rejections: int,
    ) -> None:
        event = KnowledgeRetrievalEvent(
            retrieval_event_id=f"kret-{uuid4().hex}",
            tenant_id=identity.tenant_id,
            workspace_id=identity.workspace_id,
            scenario_id=scenario_id,
            subject_id=identity.subject_id,
            query_sha256=hashlib.sha256(result.query.encode("utf-8")).hexdigest(),
            result_count=len(result.citations),
            retrieval_mode=result.retrieval_mode,
            vector_status=result.vector_status,
            cited_chunk_ids_json=json.dumps(
                [item.chunk_id for item in result.citations], ensure_ascii=False
            ),
            trace_id=result.trace_id,
            run_id=result.run_id,
            latency_ms=max(0, int((time.perf_counter() - started) * 1000)),
            rewritten_query_sha256=(
                hashlib.sha256(result.rewritten_query.encode("utf-8")).hexdigest()
                if result.rewritten_query else None
            ),
            keyword_candidate_count=keyword_candidates,
            vector_candidate_count=vector_candidates,
            injection_rejection_count=injection_rejections,
            refusal_reason=result.refusal_reason,
            context_sha256=(
                hashlib.sha256(result.context.encode("utf-8")).hexdigest()
                if result.context else None
            ),
            rank_config_json=json.dumps({
                "keyword_index": KEYWORD_INDEX,
                "embedding_model": EMBEDDING_MODEL,
                "fusion": "RRF",
                "rrf_k": RRF_K,
                "rerank": "deterministic_cross_feature_v1",
            }, sort_keys=True),
            created_at=datetime.now(UTC),
        )
        self.db.add(event)
        self.db.commit()
