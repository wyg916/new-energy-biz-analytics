import pytest

from app.response.citations import CitationValidationError
from app.response.composer import ResponseComposer
from app.response.contracts import (
    CitationEvidence,
    CompositionRequest,
    DataEvidence,
    EvidenceClaim,
    KeyMetric,
    KnowledgeEvidence,
    MemoryEvidence,
    P6ReportEvidence,
    ResponseProfileName,
)

pytestmark = pytest.mark.no_db


def citation() -> CitationEvidence:
    return CitationEvidence(
        citation_id="citation-1",
        document_id="document-1",
        document_version_id="version-1",
        chunk_id="chunk-1",
        title="经营预警制度",
        section="处置规则",
        source="docs/rules.md",
        published_at="2026-07-31T00:00:00Z",
        citation_text="已清洗且绑定版本的证据摘要",
        retrieval_score=0.94,
    )


def knowledge() -> KnowledgeEvidence:
    return KnowledgeEvidence(
        claims=(EvidenceClaim(
            claim_id="claim-1",
            text="收入下降超过制度阈值时，应先完成数据复核并分级处置。",
            citation_ids=("citation-1",),
            confidence=0.92,
        ),),
        citations=(citation(),),
        retrieval_mode="keyword_full_text_only",
        vector_status="VECTOR_DEFERRED_POST_P5",
        warnings=("向量检索待启用。",),
    )


def data() -> DataEvidence:
    return DataEvidence(
        engine="deterministic",
        scenario_id="charging_ops",
        structured_result={"revenue_change_pct": -8.2},
        key_metrics=(KeyMetric(
            metric_code="charging_revenue",
            metric_name="充电收入变化",
            value=-8.2,
            unit="%",
            source="structured_result.revenue_change_pct",
            metric_version="0.1.0",
        ),),
        conclusion="最近 30 天充电收入较上一可比周期下降 8.2%。",
        analysis=("变化值来自确定性参数化 SQL 的结构化结果。",),
        drivers=("设备状态变化与收入变化可能相关，尚无因果证据。",),
        risks=("继续下降可能触发经营预警。",),
        recommended_actions=("复核站点、时间范围和数据质量，再按制度分级处置。",),
        data_source="ACTIVE DatasetVersion / simulated",
        metric_definition=("charging_revenue v0.1.0",),
        sql="SELECT controlled_query",
        run_id="run-response-test",
    )


@pytest.mark.parametrize("profile", list(ResponseProfileName))
def test_four_profiles_return_stable_json_contract(profile) -> None:
    result = ResponseComposer().compose(CompositionRequest(
        question="最近收入变化及制度处置？",
        profile=profile,
        data_evidence=data(),
        knowledge_evidence=knowledge(),
        trace_id="trace-response-test",
        run_id="run-response-test",
        can_show_sql=True,
    ))

    assert result.refused is False
    assert result.key_metrics[0].value == -8.2
    assert result.citations or profile == ResponseProfileName.ANALYST_DETAILED
    assert result.trace_id == "trace-response-test"
    assert "模拟数据" in result.warnings[0]
    if profile == ResponseProfileName.ANALYST_DETAILED:
        assert result.sql == "SELECT controlled_query"
        assert result.metric_definition
    else:
        assert result.sql is None


def test_missing_evidence_refuses() -> None:
    result = ResponseComposer().compose(CompositionRequest(
        question="没有证据的问题",
        profile=ResponseProfileName.CONCISE_QUERY,
        trace_id="trace-response-refusal",
        run_id="run-response-refusal",
    ))

    assert result.refused is True
    assert result.confidence == 0


def test_full_integration_contract_preserves_memory_and_p6_report_evidence() -> None:
    memory = MemoryEvidence(
        working_status="ACTIVE",
        recalled_memory_ids=("MEM-1",),
        lifecycle_status="RECALLED",
        legal_hold_applied=False,
    )
    report = P6ReportEvidence(
        snapshot_id="RSE-1", report_id="RPT-1", report_version_id="RPV-1",
        analysis_run_id="ANALYSIS-1", run_id="run-response-test",
        query_plan_hash="a" * 64, sql_hash="b" * 64,
        dataset_version="1.0.0", semantic_version="1.0.1",
        snapshot_hash="c" * 64, citations=(citation(),),
    )
    result = ResponseComposer().compose(CompositionRequest(
        question="生成有证据的报告草稿",
        profile=ResponseProfileName.ANALYST_DETAILED,
        data_evidence=data(), knowledge_evidence=knowledge(),
        memory_evidence=memory, report_evidence=report,
        trace_id="trace-full-contract", run_id="run-response-test",
    ))

    assert result.memory_evidence == memory
    assert result.report_evidence == report
    assert result.citations[0].paragraph_start is None
    assert result.citations[0].locator == "document"


def test_full_integration_contract_rejects_mismatched_report_run() -> None:
    report = P6ReportEvidence(
        snapshot_id="RSE-1", report_id="RPT-1", report_version_id="RPV-1",
        analysis_run_id="ANALYSIS-1", run_id="other-run",
        query_plan_hash="a" * 64, sql_hash="b" * 64,
        dataset_version="1.0.0", semantic_version="1.0.1",
        snapshot_hash="c" * 64,
    )
    with pytest.raises(ValueError, match="report evidence run_id"):
        ResponseComposer().compose(CompositionRequest(
            question="run_id mismatch",
            profile=ResponseProfileName.ANALYST_DETAILED,
            data_evidence=data(), report_evidence=report,
            trace_id="trace-full-contract", run_id="run-response-test",
        ))


def test_unbound_claim_is_rejected() -> None:
    invalid = knowledge().model_copy(update={
        "claims": (EvidenceClaim(
            claim_id="claim-unbound",
            text="无依据结论",
            citation_ids=(),
            confidence=0.9,
        ),),
    })

    with pytest.raises(CitationValidationError):
        ResponseComposer().compose(CompositionRequest(
            question="无依据？",
            profile=ResponseProfileName.EXECUTIVE_BRIEF,
            knowledge_evidence=invalid,
            trace_id="trace-response-invalid",
            run_id="run-response-invalid",
        ))


def test_forbidden_claim_is_rejected() -> None:
    invalid = knowledge().model_copy(update={
        "claims": (EvidenceClaim(
            claim_id="claim-forbidden",
            text="平台生产环境已上线并已有真实客户。",
            citation_ids=("citation-1",),
            confidence=0.9,
        ),),
    })

    with pytest.raises(ValueError):
        ResponseComposer().compose(CompositionRequest(
            question="上线了吗？",
            profile=ResponseProfileName.EXECUTIVE_BRIEF,
            knowledge_evidence=invalid,
            trace_id="trace-response-truth",
            run_id="run-response-truth",
        ))
