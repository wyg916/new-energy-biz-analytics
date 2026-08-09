import re
from dataclasses import dataclass
from enum import StrEnum
from uuid import uuid4

from sqlalchemy.orm import Session

from app.ai.model_gateway.runtime import runtime_model_status
from app.chatbi.scenario_services import get_scenario_chat_registry
from app.knowledge.models import RetrievalIdentity
from app.knowledge.answer_guard import guard_grounded_answer
from app.knowledge.retrieval import KnowledgeRetrievalService
from app.models.auth import AuditLog, User
from app.platform.identity import IdentityContextFactory
from app.memory.episodic import EpisodicMemoryService, EpisodicRun
from app.memory.policy import MemoryPolicyService
from app.memory.working import WorkingMemoryService, WorkingMemoryState
from app.orchestration.memory_skills import MemoryContextLoader, ProcedureMatcher
from app.core.config import get_settings
from app.governance.authorization import AuthorizationService, request_context
from app.response.composer import ResponseComposer
from app.response.contracts import (
    CitationEvidence,
    CompositionRequest,
    DataEvidence,
    EvidenceClaim,
    KeyMetric,
    KnowledgeEvidence,
    ResponseProfileName,
)
from app.data.truth import current_data_truth


class CompositeRoute(StrEnum):
    DATA = "data"
    KNOWLEDGE = "knowledge"
    DATA_AND_KNOWLEDGE = "data_and_knowledge"


_KNOWLEDGE_MARKERS = ("定义", "口径", "制度", "规则", "如何处理", "怎么处理", "说明", "帮助")
_DATA_MARKERS = ("多少", "下降", "增长", "最近", "同比", "环比", "排名", "趋势", "变化")


@dataclass(frozen=True)
class CompositeResult:
    route: CompositeRoute
    response: dict
    data_query_evidence: dict | None
    knowledge_retrieval_evidence: dict | None
    model_call: dict
    trace_id: str
    run_id: str
    conversation_id: str | None
    memory_context: dict


class CompositeQueryOrchestrator:
    def __init__(self, db: Session, user: User) -> None:
        self.db = db
        self.user = user

    def execute(
        self,
        question: str,
        *,
        scenario_id: str,
        profile: ResponseProfileName,
        conversation_id: str | None = None,
        requested_route: CompositeRoute | None = None,
    ) -> CompositeResult:
        route = requested_route or self.classify(question)
        trace_id = f"TRACE-{uuid4()}"
        run_id = f"COMPOSITE-{uuid4()}"
        identity = IdentityContextFactory.from_user(self.user)
        authorizer = AuthorizationService(self.db, identity)
        if route in {CompositeRoute.DATA, CompositeRoute.DATA_AND_KNOWLEDGE}:
            for action, resource_type in (
                ("datasource.view", "datasource"),
                ("dataset.view", "dataset"),
                ("metric.query", "metric"),
            ):
                authorizer.require(request_context(
                    identity,
                    action=action,
                    resource_type=resource_type,
                    scenario_id=scenario_id,
                    environment=get_settings().app_env,
                    trace_id=trace_id,
                ))
        if route in {CompositeRoute.KNOWLEDGE, CompositeRoute.DATA_AND_KNOWLEDGE}:
            authorizer.require(request_context(
                identity,
                action="rag.document.view",
                resource_type="rag_document",
                scenario_id=scenario_id,
                environment=get_settings().app_env,
                trace_id=trace_id,
            ))
        matched_skill = ProcedureMatcher(self.db, identity).match(
            question=question,
            scenario_id=scenario_id,
        )
        loaded_memory = MemoryContextLoader(self.db, identity).load(
            scenario_id=scenario_id,
            user_question=question,
            session_id=conversation_id,
            active_procedure=(
                {
                    "skill_id": matched_skill.skill_id,
                    "skill_code": matched_skill.skill_code,
                    "version": matched_skill.version,
                }
                if matched_skill else None
            ),
        )
        data_payload = None
        data_evidence = None
        bound_conversation = conversation_id
        if route in {CompositeRoute.DATA, CompositeRoute.DATA_AND_KNOWLEDGE}:
            data_payload = get_scenario_chat_registry().execute(
                self.db,
                self.user,
                scenario_id=scenario_id,
                conversation_id=conversation_id,
                question=question,
            )
            bound_conversation = data_payload.get("conversation_id")
            data_evidence = self._adapt_data_evidence(data_payload, scenario_id, run_id)

        knowledge_result = None
        knowledge_evidence = None
        if route in {CompositeRoute.KNOWLEDGE, CompositeRoute.DATA_AND_KNOWLEDGE}:
            knowledge_result = KnowledgeRetrievalService(self.db).retrieve(
                question,
                RetrievalIdentity(
                    subject_id=identity.subject_id,
                    tenant_id=identity.tenant_id,
                    workspace_id=identity.workspace_id,
                    roles=identity.roles,
                    data_scopes=identity.data_scopes,
                ),
                scenario_id=scenario_id,
                trace_id=trace_id,
                run_id=run_id,
            )
            knowledge_evidence = self._adapt_knowledge_evidence(question, knowledge_result)

        truth = current_data_truth(self.db)
        response = ResponseComposer().compose(CompositionRequest(
            question=question,
            profile=profile,
            data_evidence=data_evidence,
            knowledge_evidence=knowledge_evidence,
            trace_id=trace_id,
            run_id=run_id,
            can_show_sql=self.user.role == "analyst_admin",
            data_classification=truth["data_classification"],
        ))
        self.db.add(AuditLog(
            actor_user_id=self.user.id,
            action="assistant.composite_query",
            resource=f"composite_query:{run_id}",
            outcome="refused" if response.refused else "success",
            detail_json=(
                '{"route":"' + route + '","scenario_id":"' + scenario_id
                + '","trace_id":"' + trace_id + '"}'
            ),
        ))
        self.db.commit()
        memory_enabled = MemoryPolicyService(self.db, identity).is_enabled(
            scenario_id=scenario_id
        )
        if memory_enabled:
            EpisodicMemoryService(self.db, identity).record_success(EpisodicRun(
                run_id=run_id,
                trace_id=trace_id,
                session_id=bound_conversation or f"COMPOSITE-{run_id}",
                raw_question=question,
                normalized_question=question.strip(),
                scenario_id=scenario_id,
                dataset_version=str(
                    ((data_payload or {}).get("query_result") or {}).get("dataset_version")
                    or "ACTIVE"
                ),
                semantic_version=str(
                    ((data_payload or {}).get("query_result") or {}).get("semantic_version")
                    or "ACTIVE"
                ),
                engine="deterministic_composite",
                query_plan=(data_payload or {}).get("query_plan") or {"route": route},
                actual_sql=((data_payload or {}).get("query_result") or {}).get("sql"),
                result_summary={
                    "route": route,
                    "refused": response.refused,
                    "data_status": (data_payload or {}).get("status"),
                    "citation_count": len(knowledge_result.citations) if knowledge_result else 0,
                },
                rag_evidence=(
                    [
                        {"chunk_id": chunk_id}
                        for chunk_id in self._safe_knowledge_evidence(knowledge_result).get("chunk_ids", [])
                    ]
                    if knowledge_result else []
                ),
                final_answer=response.conclusion,
                skill_code=matched_skill.skill_code if matched_skill else None,
                steps=[
                    {"step_id": f"STEP-{uuid4()}", "code": "identity", "status": "completed"},
                    {"step_id": f"STEP-{uuid4()}", "code": "memory_context", "status": "completed"},
                    {"step_id": f"STEP-{uuid4()}", "code": "compose", "status": "completed"},
                ],
                errors=[],
                adopted=None,
                runtime_cost={"token_usage": 0},
                latency_ms=0,
            ))
            if bound_conversation:
                working = WorkingMemoryService.from_runtime(self.db, identity).save(
                    session_id=bound_conversation,
                    state=WorkingMemoryState(
                        scenario_id=scenario_id,
                        dataset_version=str(
                            ((data_payload or {}).get("query_result") or {}).get("dataset_version")
                            or "ACTIVE"
                        ),
                        semantic_version=str(
                            ((data_payload or {}).get("query_result") or {}).get("semantic_version")
                            or "ACTIVE"
                        ),
                        metrics=list(((data_payload or {}).get("query_plan") or {}).get("metrics", [])),
                        dimensions=list(((data_payload or {}).get("query_plan") or {}).get("dimensions", [])),
                        query_result_summary={
                            "status": (data_payload or {}).get("status"),
                            "route": route,
                        },
                        knowledge_references=(
                            self._safe_knowledge_evidence(knowledge_result).get("chunk_ids", [])
                            if knowledge_result else []
                        ),
                        response_profile=profile,
                        current_intent=matched_skill.skill_code if matched_skill else None,
                        run_id=run_id,
                    ),
                )
                working_status = working.status
            else:
                working_status = loaded_memory.working_status
        else:
            working_status = "DISABLED"
        return CompositeResult(
            route=route,
            response=response.model_dump(mode="json"),
            data_query_evidence=self._safe_data_evidence(data_payload),
            knowledge_retrieval_evidence=self._safe_knowledge_evidence(knowledge_result),
            model_call={
                "status": "NOT_REQUIRED_DETERMINISTIC_COMPOSITION",
                "runtime_model_status": runtime_model_status()["status"],
            },
            trace_id=trace_id,
            run_id=run_id,
            conversation_id=bound_conversation,
            memory_context={
                "enabled": memory_enabled,
                "working_status": working_status,
                "semantic_count": len(loaded_memory.sections.semantic_facts),
                "episodic_example_count": len(loaded_memory.sections.episodic_examples),
                "matched_skill": matched_skill.skill_code if matched_skill else None,
            },
        )

    @staticmethod
    def classify(question: str) -> CompositeRoute:
        has_knowledge = any(marker in question for marker in _KNOWLEDGE_MARKERS)
        has_data = any(marker in question for marker in _DATA_MARKERS)
        if has_data and has_knowledge:
            return CompositeRoute.DATA_AND_KNOWLEDGE
        if has_knowledge:
            return CompositeRoute.KNOWLEDGE
        return CompositeRoute.DATA

    @staticmethod
    def _adapt_data_evidence(payload: dict, scenario_id: str, run_id: str) -> DataEvidence:
        result = payload.get("query_result") or {}
        rows = result.get("rows") or []
        values = rows[0] if rows else ((payload.get("result") or {}).get("metrics") or {})
        metrics = tuple(KeyMetric(
            metric_code=str(code),
            metric_name=str(code),
            value=value,
            source=f"structured_result.{code}",
            metric_version=(result.get("evidence") or {}).get("metric_versions", {}).get(code),
        ) for code, value in values.items() if isinstance(value, (int, float, str)))
        engine = result.get("engine") or "deterministic"
        evidence = result.get("evidence") or payload.get("evidence") or {}
        return DataEvidence(
            engine=engine,
            scenario_id=scenario_id,
            structured_result=payload.get("result") or {"rows": rows},
            key_metrics=metrics,
            conclusion=str(
                payload.get("answer")
                or "受控数据查询已完成，关键指标见结构化结果。"
            ),
            analysis=("查询结果已通过现有 Query Guard 与 Answer Guard 边界。",),
            drivers=(),
            risks=(),
            recommended_actions=(),
            data_source=str(evidence.get("source") or "ACTIVE published DatasetVersion"),
            metric_definition=tuple(
                f"{code} {version}"
                for code, version in (evidence.get("metric_versions") or {}).items()
            ),
            sql=result.get("sql") or evidence.get("sql"),
            run_id=run_id,
        )

    @staticmethod
    def _adapt_knowledge_evidence(question: str, result) -> KnowledgeEvidence:
        citations = tuple(CitationEvidence(
            citation_id=f"citation-{index + 1}",
            document_id=item.document_id,
            document_version_id=item.document_version_id,
            chunk_id=item.chunk_id,
            title=item.title,
            page=item.page,
            section=item.section,
            paragraph_start=item.paragraph_start,
            paragraph_end=item.paragraph_end,
            locator=item.locator,
            source=item.source,
            published_at=item.published_at.isoformat(),
            citation_text=item.citation_text,
            retrieval_score=item.retrieval_score,
        ) for index, item in enumerate(result.citations))
        claims_list = []
        for index, item in enumerate(result.citations[:3]):
            text = CompositeQueryOrchestrator._grounded_extract(question, item.citation_text)
            if not guard_grounded_answer(text, result.citations).allowed:
                continue
            claims_list.append(EvidenceClaim(
                claim_id=f"claim-{index + 1}", text=text,
                citation_ids=(f"citation-{index + 1}",),
                confidence=item.retrieval_score,
            ))
        claims = tuple(claims_list)
        return KnowledgeEvidence(
            claims=claims,
            citations=citations,
            retrieval_mode=result.retrieval_mode,
            vector_status=result.vector_status,
            warnings=result.warnings,
        )

    @staticmethod
    def _grounded_extract(question: str, content: str) -> str:
        cleaned = re.sub(r"^#+\s*", "", content.strip())
        candidates = [
            item.strip()
            for item in re.split(r"[\n。；]+", cleaned)
            if 8 <= len(item.strip()) <= 360
        ]
        query_terms = {
            question[index : index + 2]
            for index in range(max(0, len(question) - 1))
        }
        selected = next(
            (
                item for item in candidates
                if any(term in item for term in query_terms)
            ),
            candidates[0] if candidates else cleaned[:320],
        )
        return f"依据已发布文档：{selected[:360]}"

    def _safe_data_evidence(self, payload: dict | None) -> dict | None:
        if payload is None:
            return None
        result = payload.get("query_result") or {}
        safe_query_result = dict(result)
        safe_evidence = dict(payload.get("evidence") or {})
        if self.user.role != "analyst_admin":
            safe_query_result["sql"] = None
            safe_evidence["sql"] = None
        return {
            "engine": result.get("engine"),
            "run_id": result.get("run_id") or (payload.get("evidence") or {}).get("analysis_run_id"),
            "status": result.get("status") or payload.get("status"),
            "result": payload.get("result"),
            "state_version": payload.get("state_version"),
            "query_plan": payload.get("query_plan"),
            "query_result": safe_query_result,
            "evidence": safe_evidence,
            "engine_routing": payload.get("engine_routing"),
        }

    @staticmethod
    def _safe_knowledge_evidence(result) -> dict | None:
        if result is None:
            return None
        return {
            "retrieval_mode": result.retrieval_mode,
            "vector_status": result.vector_status,
            "citation_count": len(result.citations),
            "chunk_ids": [item.chunk_id for item in result.citations],
            "refusal_reason": result.refusal_reason,
            "answer_guard_status": result.answer_guard_status,
        }
