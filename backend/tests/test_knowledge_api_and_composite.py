import pytest

from app.orchestration.composite import CompositeQueryOrchestrator, CompositeRoute


def test_composite_route_classifier_supports_three_routes() -> None:
    assert CompositeQueryOrchestrator.classify("最近30天收入下降多少？") == CompositeRoute.DATA
    assert CompositeQueryOrchestrator.classify("有效订单如何定义？") == CompositeRoute.KNOWLEDGE
    assert (
        CompositeQueryOrchestrator.classify(
            "最近30天收入下降多少，按照经营预警制度应该怎么处理？"
        )
        == CompositeRoute.DATA_AND_KNOWLEDGE
    )


def test_knowledge_api_governed_flow_and_composed_answer(client, login) -> None:
    headers = login()
    catalog = client.get("/api/v1/knowledge/source-catalog", headers=headers)
    assert catalog.status_code == 200
    assert catalog.json()["automatic_workspace_scan"] is False

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
    assert retrieved.json()["vector_status"] == "VECTOR_PENDING"

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
