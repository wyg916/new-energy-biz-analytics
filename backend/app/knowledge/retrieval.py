import hashlib
import json
import time
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.knowledge.authorization import authorized_candidate_query
from app.knowledge.citation import citation_from_ranked
from app.knowledge.models import RetrievalIdentity, RetrievalResult
from app.knowledge.reranker import rank_candidates
from app.knowledge.security import prompt_injection_detected
from app.models.knowledge import KnowledgeRetrievalEvent

VECTOR_STATUS = "VECTOR_PENDING"
RETRIEVAL_MODE = "keyword_full_text_only"


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
        # Scope, publication, validity, role and data-scope predicates execute in SQL
        # before chunk content is materialized.
        candidates = list(self.db.execute(
            authorized_candidate_query(identity, scenario_id=scenario_id, at_time=now)
        ).all())
        safe_candidates = [
            item for item in candidates if not prompt_injection_detected(item[0].content)
        ]
        injection_rejections = len(candidates) - len(safe_candidates)
        ranked = rank_candidates(query, safe_candidates, limit=limit)
        citations = tuple(citation_from_ranked(item, at_time=now) for item in ranked)
        latency_ms = max(0, int((time.perf_counter() - started) * 1000))
        warnings = [
            "向量扩展当前不可用；结果仅来自关键词/全文检索，未标记为混合检索。",
        ]
        if injection_rejections:
            warnings.append(f"已隔离 {injection_rejections} 个疑似 Prompt Injection 证据块。")
        event = KnowledgeRetrievalEvent(
            retrieval_event_id=f"kret-{uuid4().hex}",
            tenant_id=identity.tenant_id,
            workspace_id=identity.workspace_id,
            scenario_id=scenario_id,
            subject_id=identity.subject_id,
            query_sha256=hashlib.sha256(query.encode("utf-8")).hexdigest(),
            result_count=len(citations),
            retrieval_mode=RETRIEVAL_MODE,
            vector_status=VECTOR_STATUS,
            cited_chunk_ids_json=json.dumps(
                [item.chunk_id for item in citations],
                ensure_ascii=False,
            ),
            trace_id=trace_id,
            run_id=run_id,
            latency_ms=latency_ms,
            created_at=datetime.now(UTC),
        )
        self.db.add(event)
        self.db.commit()
        return RetrievalResult(
            query=query,
            citations=citations,
            retrieval_mode=RETRIEVAL_MODE,
            vector_status=VECTOR_STATUS,
            trace_id=trace_id,
            run_id=run_id,
            warnings=tuple(warnings),
        )
