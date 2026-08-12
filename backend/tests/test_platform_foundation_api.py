from app.core.database import SessionLocal
from app.data.seed import generate_simulated_data


def _post(client, headers, path: str, payload: dict | None = None):
    return client.post(path, headers=headers, json=payload or {})


def test_platform_foundation_real_release_activation_and_rollback(client, login) -> None:
    with SessionLocal() as db:
        generate_simulated_data(db, session_count=300)
    headers = login()

    registered = _post(
        client,
        headers,
        "/api/v1/platform/foundation/sources",
        {
            "source_id": "platform-postgresql",
            "display_name": "PostgreSQL 平台模拟数据源",
            "source_type": "postgresql",
        },
    )
    assert registered.status_code == 200
    assert registered.json()["credential_exposed"] is False
    plaintext_rejected = _post(
        client,
        headers,
        "/api/v1/platform/foundation/sources",
        {
            "source_id": "unsafe-postgresql",
            "display_name": "unsafe",
            "source_type": "postgresql",
            "host": "example.invalid",
            "database_name": "example",
            "username": "example",
            "credential_ref": "EXAMPLE_SECRET_REF",
            "password": "must-not-be-accepted",
        },
    )
    assert plaintext_rejected.status_code == 422

    empty = client.get("/api/v1/platform/foundation", headers=headers)
    assert empty.status_code == 200
    assert empty.json()["installed"] is False

    installed = _post(client, headers, "/api/v1/platform/foundation/install")
    assert installed.status_code == 200
    initial = installed.json()["state"]
    assert initial["installed"] is True
    assert initial["scenario"]["status"] == "ACTIVE"
    assert len(initial["versions"]) == 1
    assert initial["activation"]["semantic_version"] == "0.1.0"
    dataset_id = initial["dataset"]["dataset_id"]
    v1_id = initial["activation"]["dataset_version_id"]

    discovery = client.get(
        "/api/v1/platform/foundation/sources/platform-postgresql/discover",
        headers=headers,
    )
    assert discovery.status_code == 200
    discovered = discovery.json()
    assert discovered["table_count"] == 5
    assert discovered["credential_exposed"] is False
    assert all(table["columns"] for table in discovered["schemas"][0]["tables"])

    created = _post(
        client,
        headers,
        f"/api/v1/platform/foundation/datasets/{dataset_id}/versions",
        {
            "period_start": "2025-01-01",
            "period_end_exclusive": "2026-07-01",
            "idempotency_key": "api-release-version-2-with-a-long-but-valid-idempotency-key-12345678901234567890",
        },
    )
    assert created.status_code == 200
    v2_id = created.json()["dataset_version_id"]
    assert v2_id != v1_id
    assert created.json()["state"]["versions"][0]["status"] == "QUALITY_PASSED"
    assert created.json()["state"]["versions"][0]["source_version"]

    submitted = _post(
        client, headers,
        f"/api/v1/platform/foundation/versions/{v2_id}/submit",
    )
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "PENDING"

    approved = _post(
        client, headers,
        f"/api/v1/platform/foundation/versions/{v2_id}/approve",
        {"idempotency_key": "api-approve-version-2", "reason": "P1A API test"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"

    published = _post(
        client, headers,
        f"/api/v1/platform/foundation/versions/{v2_id}/publish",
        {"idempotency_key": "api-publish-version-2"},
    )
    assert published.status_code == 200
    assert published.json()["status"] == "PUBLISHED"

    activated = _post(
        client, headers,
        f"/api/v1/platform/foundation/versions/{v2_id}/activate",
        {"idempotency_key": "api-activate-version-2", "reason": "P1A API test"},
    )
    assert activated.status_code == 200
    state = activated.json()["state"]
    assert state["activation"]["dataset_version_id"] == v2_id
    assert {item["status"] for item in state["versions"]} == {"ACTIVE", "SUPERSEDED"}

    rolled_back = _post(
        client, headers,
        f"/api/v1/platform/foundation/datasets/{dataset_id}/rollback",
        {
            "target_dataset_version_id": v1_id,
            "idempotency_key": "api-rollback-to-version-1",
            "reason": "P1A rollback verification",
        },
    )
    assert rolled_back.status_code == 200
    rollback_state = rolled_back.json()["state"]
    assert rollback_state["activation"]["dataset_version_id"] == v1_id
    assert rollback_state["rollbacks"][0]["from_dataset_version_id"] == v2_id
    assert rollback_state["rollbacks"][0]["to_dataset_version_id"] == v1_id

    rejected_version = _post(
        client,
        headers,
        f"/api/v1/platform/foundation/datasets/{dataset_id}/versions",
        {
            "period_start": "2025-01-01",
            "period_end_exclusive": "2026-07-01",
            "idempotency_key": "api-rejected-version-3",
        },
    ).json()["dataset_version_id"]
    assert _post(
        client, headers,
        f"/api/v1/platform/foundation/versions/{rejected_version}/submit",
    ).status_code == 200
    rejected = _post(
        client, headers,
        f"/api/v1/platform/foundation/versions/{rejected_version}/reject",
        {"idempotency_key": "api-reject-version-3", "reason": "negative path"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "REJECTED"
    cannot_publish = _post(
        client, headers,
        f"/api/v1/platform/foundation/versions/{rejected_version}/publish",
        {"idempotency_key": "api-publish-rejected-version-3"},
    )
    assert cannot_publish.status_code == 409


def test_platform_foundation_requires_admin_role(client, login) -> None:
    headers = login("regional", "AlphaRegion!2026")
    assert client.get("/api/v1/platform/foundation", headers=headers).status_code == 403
