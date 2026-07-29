from app.core.logging import JsonFormatter


def test_readiness_fails_closed_without_redis_and_redacts_connections(client):
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["data_classification"] == "simulated"
    assert set(body["components"]) == {"database", "redis"}
    serialized = response.text.lower()
    assert "database_url" not in serialized
    assert "redis_url" not in serialized
    assert "password" not in serialized


def test_readiness_returns_200_when_dependencies_and_revision_are_ready(client, monkeypatch):
    monkeypatch.setattr(
        "app.api.router.readiness_snapshot",
        lambda: (
            {
                "status": "ready",
                "service": "renewable-operations-api",
                "release_version": "0.6.0-rc1",
                "data_classification": "simulated",
                "components": {
                    "database": {"status": "ok", "revision": "0006", "expected_revision": "0006"},
                    "redis": {"status": "ok"},
                },
            },
            200,
        ),
    )
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json()["components"]["database"]["revision"] == "0006"


def test_prometheus_metrics_are_low_cardinality(client):
    client.get("/api/v1/health")
    response = client.get("/api/v1/metrics")
    assert response.status_code == 200
    body = response.text
    assert "renewable_api_http_requests_total" in body
    assert 'method="GET"' in body
    assert "path=" not in body
    assert "username" not in body


def test_json_formatter_includes_only_explicit_safe_context():
    import logging
    import json

    record = logging.LogRecord("app.http", logging.INFO, "", 0, "http_request", (), None)
    record.context = {"request_id": "REQ-safe", "path": "/api/v1/health"}
    payload = json.loads(JsonFormatter().format(record))
    assert payload["context"] == {"request_id": "REQ-safe", "path": "/api/v1/health"}
