from app.response.citations import citations_for_claims
from app.response.contracts import CompositionRequest, FinalResponse
from app.response.profiles import PROFILES
from app.response.safety import clamp_text, enforce_truthfulness
from app.response.validators import validate_composition_request


class ResponseComposer:
    """Deterministic final-answer boundary over already verified evidence."""

    def compose(self, request: CompositionRequest) -> FinalResponse:
        validate_composition_request(request)
        profile = PROFILES[request.profile]
        if request.data_evidence is None and request.knowledge_evidence is None:
            return self._refusal(request, "缺少可验证的数据结果或已发布知识证据，无法形成可靠回答。")

        data = request.data_evidence
        knowledge = request.knowledge_evidence
        claims = knowledge.claims if knowledge else ()
        if knowledge is not None and not claims and data is None:
            return self._refusal(request, "未检索到可支持结论的已发布知识证据。")

        conclusion_parts: list[str] = []
        if data and data.conclusion:
            conclusion_parts.append(data.conclusion)
        conclusion_parts.extend(claim.text for claim in claims)
        if not conclusion_parts and data:
            conclusion_parts.append("已完成受控数据查询，关键结果见指标明细。")
        conclusion = " ".join(
            enforce_truthfulness(part, profile) for part in conclusion_parts
        )
        conclusion = clamp_text(conclusion, profile.max_chars)

        warnings = [self._classification_warning(request.data_classification)]
        if knowledge:
            warnings.extend(knowledge.warnings)
        if data and data.engine == "sqlbot":
            warnings.append("SQLBot 结果仅在通过 Query Guard 与结构化结果校验后使用。")

        citations = citations_for_claims(claims, knowledge.citations) if (
            knowledge and profile.show_citations
        ) else ()
        confidence_parts = [claim.confidence for claim in claims]
        if data:
            confidence_parts.append(1.0)
        confidence = round(min(confidence_parts), 4) if confidence_parts else 0.0

        analysis = tuple(
            enforce_truthfulness(item, profile) for item in (data.analysis if data else ())
        )
        evidence = tuple(
            f"{claim.claim_id}: {', '.join(claim.citation_ids)}" for claim in claims
        )
        if data:
            evidence = (f"structured_result:{data.run_id}:{data.engine}",) + evidence
        return FinalResponse(
            conclusion=conclusion,
            key_metrics=data.key_metrics if data else (),
            analysis=analysis,
            drivers=tuple(
                enforce_truthfulness(item, profile) for item in (data.drivers if data else ())
            ),
            evidence=evidence,
            risks=tuple(
                enforce_truthfulness(item, profile) for item in (data.risks if data else ())
            ),
            recommended_actions=tuple(
                enforce_truthfulness(item, profile)
                for item in (data.recommended_actions if data and profile.generate_actions else ())
            ),
            data_source=(data.data_source,) if data and profile.show_data_source else (),
            metric_definition=data.metric_definition if (
                data and profile.show_metric_definition
            ) else (),
            citations=citations,
            warnings=tuple(dict.fromkeys(warnings)),
            confidence=confidence if profile.show_confidence else 0.0,
            trace_id=request.trace_id,
            run_id=request.run_id,
            profile=request.profile,
            sql=data.sql if (
                data and profile.show_sql and request.can_show_sql
            ) else None,
            refused=False,
            data_classification=request.data_classification,
        )

    def _refusal(self, request: CompositionRequest, message: str) -> FinalResponse:
        return FinalResponse(
            conclusion=message,
            key_metrics=(),
            analysis=(),
            drivers=(),
            evidence=(),
            risks=(),
            recommended_actions=(),
            data_source=(),
            metric_definition=(),
            citations=(),
            warnings=(self._classification_warning(request.data_classification),),
            confidence=0.0,
            trace_id=request.trace_id,
            run_id=request.run_id,
            profile=request.profile,
            sql=None,
            refused=True,
            data_classification=request.data_classification,
        )

    @staticmethod
    def _classification_warning(data_classification: str) -> str:
        if data_classification == "open_source_real_data":
            return "当前展示数据来自已登记公开数据样本；来源、许可、版本和转换血缘可审计。"
        return "当前展示数据均为固定随机种子生成的模拟数据。"
