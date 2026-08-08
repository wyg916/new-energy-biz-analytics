import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.memory.api as memory_api
from app.memory.models import MEMORY_LIFECYCLE_TABLES, P2B_MEMORY_TABLES
from app.models.auth import User


pytestmark = pytest.mark.no_db


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    for table in [*P2B_MEMORY_TABLES, *MEMORY_LIFECYCLE_TABLES]:
        table.create(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as session:
        yield session
    engine.dispose()


def user(role="analyst_admin"):
    return User(
        id=1,
        username="lifecycle-admin",
        password_hash="x",
        display_name="Lifecycle Admin",
        role=role,
        region_code=None,
        is_active=True,
    )


def test_memory_lifecycle_admin_read_only_handlers_omit_content(db, monkeypatch):
    monkeypatch.setattr(memory_api, "_require", lambda *args, **kwargs: None)
    assert memory_api.lifecycle_tasks(None, 50, db, user()) == {"tasks": []}
    metrics = memory_api.lifecycle_metrics(db, user())
    assert metrics["content_included"] is False
    assert "records" not in metrics


def test_memory_lifecycle_admin_handlers_deny_business_role(db):
    with pytest.raises(HTTPException) as error:
        memory_api.lifecycle_tasks(None, 50, db, user("executive"))
    assert error.value.status_code == 403
    assert error.value.detail["code"] == "MEMORY_LIFECYCLE_ADMIN_REQUIRED"
