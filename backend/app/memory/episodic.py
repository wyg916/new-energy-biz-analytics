from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.memory.audit import audit_memory_use
from app.memory.authorization import MemoryAuthorization
from app.memory.contracts import MemoryScope, MemoryStatus, MemoryType, TrustLevel
from app.memory.models import MemoryRecord
from app.platform.identity import IdentityContext


class EpisodicMemoryError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class EpisodicRun:
    run_id: str
    trace_id: str
    session_id: str
    raw_question: str
    normalized_question: str
    scenario_id: str
    dataset_version: str
    semantic_version: str
    engine: str
    query_plan: dict
    actual_sql: str | None
    result_summary: dict
    rag_evidence: list[dict]
    final_answer: str
    skill_code: str | None
    steps: list[dict]
    errors: list[dict]
    adopted: bool | None
    runtime_cost: dict
    latency_ms: int


class EpisodicMemoryService:
    def __init__(self, db: Session, identity: IdentityContext) -> None:
        self.db = db
        self.identity = identity

    def record_success(self, episode: EpisodicRun) -> MemoryRecord:
        if "SHADOW" in episode.engine.upper():
            raise EpisodicMemoryError(
                "SQLBOT_SHADOW_FACT_FORBIDDEN",
                "SQLBot Shadow 结果只能保存在评测证据中",
            )
        if any(key in episode.result_summary for key in ("rows", "records", "raw_result")):
            raise EpisodicMemoryError(
                "EPISODIC_DETAIL_RESULT_FORBIDDEN",
                "情景记忆只能保存结果摘要，不能保存完整明细结果",
            )
        scope = MemoryAuthorization.scope_from_identity(
            self.identity,
            MemoryScope.RUN,
            scenario_id=episode.scenario_id,
            session_id=episode.session_id,
            run_id=episode.run_id,
        )
        existing = self.db.scalar(select(MemoryRecord).where(
            MemoryRecord.memory_type == MemoryType.EPISODIC,
            MemoryRecord.tenant_id == scope.tenant_id,
            MemoryRecord.workspace_id == scope.workspace_id,
            MemoryRecord.user_id == scope.user_id,
            MemoryRecord.run_id == episode.run_id,
            MemoryRecord.status == MemoryStatus.ACTIVE,
        ))
        if existing:
            return existing
        result_hash = hashlib.sha256(
            json.dumps(episode.result_summary, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        structured = {
            "raw_question": episode.raw_question,
            "normalized_question": episode.normalized_question,
            "scenario_id": episode.scenario_id,
            "dataset_version": episode.dataset_version,
            "semantic_version": episode.semantic_version,
            "engine": episode.engine,
            "query_plan": episode.query_plan,
            "actual_sql": episode.actual_sql,
            "result_summary": episode.result_summary,
            "result_hash": result_hash,
            "rag_evidence": episode.rag_evidence,
            "final_answer": episode.final_answer,
            "skill_code": episode.skill_code,
            "steps": episode.steps,
            "errors": episode.errors,
            "adopted": episode.adopted,
            "runtime_cost": episode.runtime_cost,
            "latency_ms": episode.latency_ms,
            "trace_id": episode.trace_id,
        }
        duplicate_hash = hashlib.sha256(
            f"{scope.tenant_id}|{scope.workspace_id}|{scope.user_id}|{episode.run_id}".encode("utf-8")
        ).hexdigest()
        record = MemoryRecord(
            memory_id=f"MEM-{uuid4()}",
            memory_type=MemoryType.EPISODIC,
            scope_type=scope.scope_type,
            tenant_id=scope.tenant_id,
            organization_id=scope.organization_id,
            workspace_id=scope.workspace_id,
            user_id=scope.user_id,
            session_id=episode.session_id,
            run_id=episode.run_id,
            scenario_id=episode.scenario_id,
            content=episode.normalized_question,
            structured_value_json=json.dumps(structured, ensure_ascii=False, sort_keys=True),
            source_type="ANALYSIS_RUN",
            source_id=episode.run_id,
            trust_level=TrustLevel.SYSTEM_VERIFIED,
            confidence=1.0,
            importance=0.7,
            status=MemoryStatus.ACTIVE,
            version=1,
            duplicate_hash=duplicate_hash,
            retention_policy="ANALYSIS_HISTORY",
            approval_required=False,
        )
        self.db.add(record)
        audit_memory_use(
            self.db,
            self.identity,
            action="episodic.write",
            outcome="success",
            memory_id=record.memory_id,
            run_id=episode.run_id,
            trace_id=episode.trace_id,
            detail={"result_hash": result_hash, "skill_code": episode.skill_code},
        )
        self.db.commit()
        return record

    def replay(self, *, run_id: str, scenario_id: str) -> dict:
        record = self.db.scalar(select(MemoryRecord).where(
            MemoryAuthorization.retrieval_filter(self.identity, scenario_id=scenario_id),
            MemoryRecord.memory_type == MemoryType.EPISODIC,
            MemoryRecord.run_id == run_id,
            MemoryRecord.status == MemoryStatus.ACTIVE,
            MemoryRecord.deleted_at.is_(None),
        ))
        if record is None:
            raise EpisodicMemoryError("EPISODE_NOT_FOUND", "当前身份范围内未找到运行记录")
        MemoryAuthorization.assert_owned(self.identity, record)
        MemoryAuthorization.assert_scenario(record, scenario_id)
        audit_memory_use(
            self.db,
            self.identity,
            action="episodic.replay",
            outcome="success",
            memory_id=record.memory_id,
            run_id=run_id,
            commit=True,
        )
        return json.loads(record.structured_value_json)

    def search(self, *, query: str, scenario_id: str, limit: int = 20) -> list[dict]:
        safe_limit = min(max(limit, 1), 50)
        records = self.db.scalars(select(MemoryRecord).where(
            MemoryAuthorization.retrieval_filter(self.identity, scenario_id=scenario_id),
            MemoryRecord.memory_type == MemoryType.EPISODIC,
            MemoryRecord.status == MemoryStatus.ACTIVE,
            MemoryRecord.deleted_at.is_(None),
            MemoryRecord.content.ilike(f"%{query[:100]}%"),
        ).order_by(desc(MemoryRecord.created_at)).limit(safe_limit)).all()
        audit_memory_use(
            self.db,
            self.identity,
            action="episodic.search",
            outcome="success",
            detail={"scenario_id": scenario_id, "result_count": len(records)},
            commit=True,
        )
        return [json.loads(record.structured_value_json) for record in records]
