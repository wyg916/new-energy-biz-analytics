import os
from pathlib import Path

os.environ.update({
    "APP_ENV": "test",
    "DATABASE_URL": os.environ.get(
        "TEST_DATABASE_URL",
        "sqlite:///./data/test.db",
    ),
    "SECRET_KEY": "test-secret-key-not-for-production",
    "AUTO_BOOTSTRAP_DEMO_USERS": "true",
})
Path("data").mkdir(exist_ok=True)

import pytest
from fastapi.testclient import TestClient

from app.core.database import Base, engine
from app.main import app


@pytest.fixture(autouse=True)
def clean_database(request):
    if request.node.get_closest_marker("no_db"):
        yield
        return
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def login(client):
    def _login(username="analyst", password="AlphaAnalyst!2026"):
        response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
        assert response.status_code == 200
        return {"Authorization": f"Bearer {response.json()['access_token']}"}
    return _login
