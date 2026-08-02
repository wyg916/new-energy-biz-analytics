import pytest
from types import SimpleNamespace

from app.orchestration.composite import CompositeQueryOrchestrator, CompositeRoute
from app.scenarios.sales_ops.engine import SalesOpsQueryError


def test_composite_route_classifier_supports_three_routes() -> None:
    assert CompositeQueryOrchestrator.classify("最近30天收入下降多少？") == CompositeRoute.DATA
    assert CompositeQueryOrchestrator.classify("有效订单如何定义？") == CompositeRoute.KNOWLEDGE
    assert (
        CompositeQueryOrchestrator.classify(
            "最近30天收入下降多少，按照经营预警制度应该怎么处理？"
        )
        == CompositeRoute.DATA_AND_KNOWLEDGE
    )


def test_data_route_preserves_and_role_redacts_governed_engine_evidence() -> None:
    payload = {
        "status": "completed",
        "state_version": 2,
        "result": {"metrics": {"charging_revenue": 100}},
        "query_plan": {"intent": "metric_lookup"},
        "query_result": {
            "engine": "deterministic",
            "run_id": "CHAT-evidence",
            "status": "completed",
            "scenario": "charging_ops",
            "dataset_version": "2",
            "semantic_version": "1.0.0",
            "sql": "SELECT governed_metric",
        },
        "evidence": {
            "analysis_run_id": "CHAT-evidence",
            "query_guard": "passed",
            "answer_guard": {"status": "passed"},
            "sql": "SELECT governed_metric",
        },
        "engine_routing": {"mode": "SHADOW"},
    }
    orchestrator = object.__new__(CompositeQueryOrchestrator)
    orchestrator.user = SimpleNamespace(role="analyst_admin")
    evidence = orchestrator._safe_data_evidence(payload)

    assert evidence["run_id"].startswith("CHAT-")
    assert evidence["evidence"]["analysis_run_id"] == evidence["run_id"]
    assert evidence["evidence"]["query_guard"] == "passed"
    assert evidence["evidence"]["answer_guard"]["status"] == "passed"
    assert evidence["query_result"]["scenario"] == "charging_ops"
    assert evidence["query_result"]["dataset_version"]
    assert evidence["query_result"]["semantic_version"]
    assert evidence["engine_routing"]["mode"] == "SHADOW"
    assert evidence["query_result"]["sql"] == "SELECT governed_metric"

    orchestrator.user = SimpleNamespace(role="executive")
    redacted = orchestrator._safe_data_evidence(payload)
    assert redacted["query_result"]["sql"] is None
    assert redacted["evidence"]["sql"] is None


def test_assistant_maps_scenario_query_errors_to_safe_contract(
    client,
    login,
    monkeypatch,
) -> None:
    def reject(*args, **kwargs):
        raise SalesOpsQueryError("METRIC_AMBIGUOUS", "请明确销售指标")

    monkeypatch.setattr(CompositeQueryOrchestrator, "execute", reject)
    response = client.post(
        "/api/v1/assistant/query",
        headers=login(),
        json={
            "question": "2026年6月表现如何？",
            "scenario_id": "sales_ops",
            "profile": "analyst_detailed",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "METRIC_AMBIGUOUS",
        "message": "请明确销售指标",
    }


def test_knowledge_api_governed_flow_and_composed_answer(client, login) -> None:
    headers = login()
    catalog = client.get("/api/v1/knowledge/source-catalog", headers=headers)
    assert catalog.status_code == 200
    assert catalog.json()["automatic_workspace_scan"] is False
    assert "docs/platformization/p1b/06_SALES_OPS_SCENARIO.md" in (
        catalog.json()["sources"]
    )
    assert "docs/v2/V2_business_alerts_UI_acceptance.md" in (
        catalog.json()["sources"]
    )

    created = client.post(
        "/api/v1/knowledge/documents/ingest",
        headers=headers,
        json={
            "source_path": "docs/metric_dictionary_v0.1.md",
            "title": "指标字典 v0.1",
            "scenario_id": "charging_ops",
            "knowledge_domain": "metric_definition",
            "roles": ["analyst_admin"],
            "data_scopes": ["workspace:all"],
        },
    )
    assert created.status_code == 200, created.text
    version_id = created.json()["document_version_id"]
    assert created.json()["status"] == "READY"

    unpublished = client.post(
        "/api/v1/knowledge/retrieval/test",
        headers=headers,
        json={
            "query": "充电收入 指标定义",
            "scenario_id": "charging_ops",
            "trace_id": "trace-api-unpublished",
        },
    )
    assert unpublished.status_code == 200
    assert unpublished.json()["citations"] == []

    published = client.post(
        f"/api/v1/knowledge/versions/{version_id}/publish",
        headers=headers,
        json={"reason": "API acceptance"},
    )
    assert published.status_code == 200
    assert published.json()["status"] == "PUBLISHED"

    retrieved = client.post(
        "/api/v1/knowledge/retrieval/test",
        headers=headers,
        json={
            "query": "充电收入 指标定义",
            "scenario_id": "charging_ops",
            "trace_id": "trace-api-published",
        },
    )
    assert retrieved.status_code == 200
    assert retrieved.json()["citations"]
    assert retrieved.json()["vector_status"] == "VECTOR_DEFERRED_POST_P5"

    answered = client.post(
        "/api/v1/assistant/query",
        headers=headers,
        json={
            "question": "充电收入如何定义？",
            "scenario_id": "charging_ops",
            "profile": "analyst_detailed",
            "route": "knowledge",
        },
    )
    assert answered.status_code == 200, answered.text
    body = answered.json()
    assert body["route"] == "knowledge"
    assert body["response"]["refused"] is False
    assert body["response"]["citations"]
    assert body["model_call"]["runtime_model_status"] == "MODEL_RUNTIME_PENDING"

    retired = client.post(
        f"/api/v1/knowledge/versions/{version_id}/retire",
        headers=headers,
        json={"reason": "API retirement acceptance"},
    )
    assert retired.status_code == 200
    assert retired.json()["status"] == "RETIRED"
    deleted = client.post(
        f"/api/v1/knowledge/versions/{version_id}/delete",
        headers=headers,
        json={"reason": "API logical deletion acceptance"},
    )
    assert deleted.status_code == 200
    assert deleted.json()["deletion_mode"] == "logical_audit_preserving"

    after_retire = client.post(
        "/api/v1/knowledge/retrieval/test",
        headers=headers,
        json={
            "query": "充电收入 指标定义",
            "scenario_id": "charging_ops",
            "trace_id": "trace-api-retired",
        },
    )
    assert after_retire.status_code == 200
    assert after_retire.json()["citations"] == []


def test_untracked_user_source_document_is_rejected_by_api(client, login) -> None:
    headers = login()
    response = client.post(
        "/api/v1/knowledge/documents/ingest",
        headers=headers,
        json={
            "source_path": "RAG企业知识库_知识体系与企业级开发实施指南_v1.0.docx",
            "title": "不得自动导入",
            "scenario_id": "charging_ops",
            "knowledge_domain": "system_help",
            "roles": ["analyst_admin"],
            "data_scopes": ["workspace:all"],
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "KNOWLEDGE_SOURCE_DENIED"
