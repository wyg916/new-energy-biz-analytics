from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.memory.audit import audit_memory_use
from app.memory.authorization import MemoryAuthorization
from app.memory.contracts import ContextSections, MemoryStatus, MemoryType
from app.memory.models import MemoryRecord
from app.memory.policy import MemoryPolicyService
from app.memory.procedural import SkillRegistry
from app.memory.retrieval import ContextAssembler, MemoryRetriever
from app.memory.working import WorkingMemoryService, WorkingMemoryState
from app.models.auth import User
from app.platform.identity import IdentityContext, IdentityContextFactory
from app.skills.contracts import SkillOutput, SkillRequest
from app.skills.runtime import SkillExecutor


@dataclass(frozen=True)
class LoadedMemoryContext:
    sections: ContextSections
    working_status: str
    memory_enabled: bool


class MemoryContextLoader:
    def __init__(self, db: Session, identity: IdentityContext) -> None:
        self.db = db
        self.identity = identity

    def load(
        self,
        *,
        scenario_id: str,
        user_question: str,
        session_id: str | None,
        active_procedure: dict | None = None,
        current_data: dict | None = None,
        rag_evidence: tuple[dict, ...] = (),
    ) -> LoadedMemoryContext:
        enabled = MemoryPolicyService(self.db, self.identity).is_enabled(
            scenario_id=scenario_id
        )
        if not enabled:
            return LoadedMemoryContext(
                sections=ContextAssembler.assemble(
                    self.identity,
                    active_procedure=active_procedure,
                    semantic_records=(),
                    episodic_records=(),
                    working_state={"status": "DISABLED"},
                    current_data=current_data or {},
                    rag_evidence=rag_evidence,
                    user_question=user_question,
                ),
                working_status="DISABLED",
                memory_enabled=False,
            )
        retriever = MemoryRetriever(self.db, self.identity)
        semantic = retriever.retrieve(
            scenario_id=scenario_id,
            memory_types=(MemoryType.SEMANTIC,),
            token_budget=800,
            limit=10,
        )
        episodic = retriever.retrieve(
            scenario_id=scenario_id,
            memory_types=(MemoryType.EPISODIC,),
            query=user_question[:40],
            token_budget=800,
            limit=5,
        )
        working_state = {}
        working_status = "NOT_REQUESTED"
        if session_id:
            working = WorkingMemoryService.from_runtime(self.db, self.identity).load(
                scenario_id=scenario_id,
                session_id=session_id,
            )
            working_status = working.status
            working_state = (
                working.state.model_dump(mode="json") if working.state else {}
            )
        return LoadedMemoryContext(
            sections=ContextAssembler.assemble(
                self.identity,
                active_procedure=active_procedure,
                semantic_records=semantic.records,
                episodic_records=episodic.records,
                working_state=working_state,
                current_data=current_data or {},
                rag_evidence=rag_evidence,
                user_question=user_question,
            ),
            working_status=working_status,
            memory_enabled=True,
        )


class ProcedureMatcher:
    MARKERS = {
        "revenue_decline_diagnosis": ("收入下降", "营收下降", "revenue decline"),
        "order_anomaly_analysis": ("订单异常", "单量异常", "order anomaly"),
        "gross_profit_change_decomposition": ("毛利变化", "毛利拆解", "gross profit change"),
        "station_efficiency_diagnosis": ("场站效率", "利用率诊断", "station efficiency"),
        "operating_report_generation": ("生成报告", "经营报告", "operating report"),
    }

    def __init__(self, db: Session, identity: IdentityContext) -> None:
        self.registry = SkillRegistry(db, identity)

    def match(self, *, question: str, scenario_id: str):
        lowered = question.lower()
        for skill_code, markers in self.MARKERS.items():
            if any(marker.lower() in lowered for marker in markers):
                return self.registry.match(skill_code=skill_code, scenario_id=scenario_id)
        return None


class FeedbackHandler:
    def __init__(self, db: Session, identity: IdentityContext) -> None:
        self.db = db
        self.identity = identity

    def record(
        self,
        *,
        run_id: str,
        trace_id: str,
        rating: str,
        comment: str | None,
        scenario_id: str,
    ) -> dict:
        episode = self.db.scalar(select(MemoryRecord).where(
            MemoryAuthorization.retrieval_filter(self.identity, scenario_id=scenario_id),
            MemoryRecord.memory_type == MemoryType.EPISODIC,
            MemoryRecord.run_id == run_id,
            MemoryRecord.status == MemoryStatus.ACTIVE,
            MemoryRecord.deleted_at.is_(None),
        ))
        if episode is None:
            raise LookupError("EPISODE_NOT_FOUND")
        value = json.loads(episode.structured_value_json)
        value["feedback"] = {
            "rating": rating,
            "comment": comment,
            "trace_id": trace_id,
        }
        value["adopted"] = rating == "helpful"
        episode.structured_value_json = json.dumps(
            value, ensure_ascii=False, sort_keys=True
        )
        audit_memory_use(
            self.db,
            self.identity,
            action="memory.feedback",
            outcome=rating,
            memory_id=episode.memory_id,
            run_id=run_id,
            trace_id=trace_id,
            detail={"has_comment": bool(comment)},
        )
        self.db.commit()
        return {"status": "recorded", "rating": rating, "run_id": run_id}


class MemorySkillOrchestrator:
    def __init__(self, db: Session, user: User) -> None:
        self.db = db
        self.user = user
        self.identity = IdentityContextFactory.from_user(user)

    def execute(self, request: SkillRequest) -> dict:
        run_id = request.run_id or f"SKRUN-{uuid4()}"
        trace_id = request.trace_id or f"TRACE-{uuid4()}"
        request = request.model_copy(update={"run_id": run_id, "trace_id": trace_id})
        match = SkillRegistry(self.db, self.identity).match(
            skill_code=request.skill_code,
            scenario_id=request.scenario_id,
        )
        if match is None:
            raise LookupError("SKILL_NOT_ACTIVE")
        context = MemoryContextLoader(self.db, self.identity).load(
            scenario_id=request.scenario_id,
            user_question=f"执行 {request.skill_code}",
            session_id=request.session_id,
            active_procedure={
                "skill_id": match.skill_id,
                "skill_code": match.skill_code,
                "version": match.version,
                "status": match.status,
            },
        )
        output = SkillExecutor(self.db, self.user).execute(request)
        working_status = context.working_status
        if request.session_id and context.memory_enabled:
            working = WorkingMemoryService.from_runtime(self.db, self.identity).save(
                session_id=request.session_id,
                state=WorkingMemoryState(
                    scenario_id=request.scenario_id,
                    time_range={
                        "start": request.start.isoformat(),
                        "end_exclusive": request.end_exclusive.isoformat(),
                    },
                    metrics=[
                        output.metric_change.get("metric_id")
                    ] if output.metric_change.get("metric_id") else list(
                        (output.metric_change.get("metrics") or {}).keys()
                    ),
                    dimensions=[request.dimension] if request.dimension else [],
                    query_result_summary={
                        "metric_change": output.metric_change,
                        "anomaly_count": len(output.anomalies),
                    },
                    current_intent=request.skill_code,
                    run_id=run_id,
                ),
            )
            working_status = working.status
        return {
            "output": output.model_dump(mode="json"),
            "memory": {
                "enabled": context.memory_enabled,
                "working_status": working_status,
                "semantic_count": len(context.sections.semantic_facts),
                "episodic_example_count": len(context.sections.episodic_examples),
            },
        }
