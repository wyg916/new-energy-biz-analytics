import hashlib
import json
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main_module
import app.governance.identity as identity_module
from app.api.dependencies import current_user
from app.core.database import Base, get_db
from app.core.security import hash_password
from app.main import app
from app.models.auth import User
from app.governance.bootstrap import install_governance_baseline
from app.platform.identity import IdentityContextFactory
from app.memory.models import MemoryRecord
from app.skills.definitions import install_initial_skills


pytestmark = pytest.mark.no_db


@pytest.fixture
def api_client(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        users = (
            User(username="analyst", password_hash=hash_password("AlphaAnalyst!2026"), display_name="分析师", role="analyst_admin", region_code=None, is_active=True),
            User(username="executive", password_hash=hash_password("AlphaExec!2026"), display_name="经营负责人", role="executive", region_code=None, is_active=True),
        )
        db.add_all(users)
        db.commit()
        install_governance_baseline(db)
        install_initial_skills(db, IdentityContextFactory.from_user(users[0]))

    def override_db():
        with factory() as db:
            yield db

    monkeypatch.setattr(main_module, "bootstrap_demo_users", lambda: None)
    monkeypatch.setattr(identity_module, "SessionLocal", factory)
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        client.test_session_factory = factory
        yield client
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def api_login(api_client):
    def login(username="analyst", password="AlphaAnalyst!2026"):
        response = api_client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return login


def test_memory_preference_confirm_correct_and_delete_api(api_client, api_login):
    headers = api_login()
    proposed = api_client.post(
        "/api/v1/memory/preferences",
        headers=headers,
        json={
            "key": "answer_style",
            "value": "简洁",
            "confirmed": True,
            "write_reason": "用户明确偏好",
        },
    )
    assert proposed.status_code == 200, proposed.text
    confirmed = api_client.post(
        f"/api/v1/memory/candidates/{proposed.json()['candidate_id']}/confirm",
        headers=headers,
    )
    assert confirmed.status_code == 200, confirmed.text
    memory_id = confirmed.json()["memory_id"]
    listed = api_client.get(
        "/api/v1/memory/records?scenario_id=charging_ops&memory_type=SEMANTIC",
        headers=headers,
    )
    assert any(item["memory_id"] == memory_id for item in listed.json()["records"])
    deleted = api_client.delete(
        f"/api/v1/memory/records/{memory_id}?reason=用户删除",
        headers=headers,
    )
    assert deleted.status_code == 200
    after = api_client.get(
        "/api/v1/memory/records?scenario_id=charging_ops&memory_type=SEMANTIC",
        headers=headers,
    )
    assert all(item["memory_id"] != memory_id for item in after.json()["records"])


def test_memory_management_list_keeps_new_record_visible_after_recall_candidate_cap(api_client, api_login):
    headers = api_login()
    with api_client.test_session_factory() as db:
        user = db.scalar(select(User).where(User.username == "analyst"))
        identity = IdentityContextFactory.from_user(user)
        older = datetime(2025, 1, 1, tzinfo=UTC)
        db.add_all([
            MemoryRecord(
                memory_id=f"MEM-LIST-{index:03d}",
                memory_type="EPISODIC",
                scope_type="USER",
                tenant_id=identity.tenant_id,
                organization_id=identity.org_id,
                workspace_id=identity.workspace_id,
                user_id=identity.subject_id,
                scenario_id="charging_ops",
                content=f"historical high-importance record {index}",
                structured_value_json=json.dumps({"run_id": f"RUN-LIST-{index:03d}"}),
                source_type="ANALYSIS_RUN",
                source_id=f"RUN-LIST-{index:03d}",
                trust_level="SYSTEM_VERIFIED",
                confidence=1.0,
                importance=1.0,
                status="ACTIVE",
                version=1,
                duplicate_hash=hashlib.sha256(f"list-{index}".encode()).hexdigest(),
                retention_policy="STANDARD",
                approval_required=False,
                valid_from=older,
                created_at=older,
                updated_at=older,
            )
            for index in range(120)
        ])
        db.commit()
    proposed = api_client.post(
        "/api/v1/memory/preferences",
        headers=headers,
        json={
            "key": "corrected_term",
            "value": "最近创建的可管理记忆",
            "confirmed": True,
            "write_reason": "验证管理列表不受召回候选上限影响",
        },
    )
    assert proposed.status_code == 200, proposed.text
    confirmed = api_client.post(
        f"/api/v1/memory/candidates/{proposed.json()['candidate_id']}/confirm",
        headers=headers,
    )
    assert confirmed.status_code == 200, confirmed.text
    memory_id = confirmed.json()["memory_id"]
    listed = api_client.get(
        "/api/v1/memory/records?scenario_id=charging_ops",
        headers=headers,
    )
    assert listed.status_code == 200, listed.text
    payload = listed.json()
    assert payload["total"] >= 121
    assert payload["truncated"] is False
    assert payload["records"][0]["memory_id"] == memory_id
    assert any(item["memory_id"] == memory_id for item in payload["records"])


def test_memory_disable_setting_is_enforced(api_client, api_login):
    headers = api_login()
    disabled = api_client.put(
        "/api/v1/memory/settings",
        headers=headers,
        json={"enabled": False},
    )
    assert disabled.status_code == 200, disabled.text
    listed = api_client.get(
        "/api/v1/memory/records?scenario_id=charging_ops",
        headers=headers,
    )
    assert listed.json()["memory_enabled"] is False


def test_initial_skills_are_bootstrapped_and_visible(api_client, api_login):
    response = api_client.get("/api/v1/skills?scenario_id=charging_ops", headers=api_login())
    assert response.status_code == 200, response.text
    skills = response.json()["skills"]
    assert len(skills) == 5
    assert all(item["status"] == "ACTIVE" and item["enabled"] for item in skills)
    assert all(item["steps"] and item["validations"] for item in skills)


def test_unimplemented_skill_controls_are_truthfully_disabled(api_client, api_login):
    response = api_client.get("/api/v1/skills?scenario_id=charging_ops", headers=api_login())
    skill = response.json()["skills"][0]
    assert skill["controls"]["can_enable"] is False
    assert skill["controls"]["can_disable"] is True
    assert skill["controls"]["can_rollback"] is False


def test_non_admin_cannot_install_or_disable_skill(api_client, api_login):
    executive = api_login(username="executive", password="AlphaExec!2026")
    install = api_client.post("/api/v1/skills/install-initial", headers=executive)
    assert install.status_code == 403
    skills = api_client.get("/api/v1/skills?scenario_id=charging_ops", headers=executive).json()["skills"]
    assert all(not any(item["controls"].values()) for item in skills)
    disabled = api_client.post(f"/api/v1/skills/{skills[0]['skill_id']}/disable", headers=executive)
    assert disabled.status_code == 403
