from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.memory.models import MemoryAuditEvent
from app.platform.identity import IdentityContext
from app.query_engines.sqlbot.source_binding import (
    SQLBotSourceBindingRegistry,
    SourceBindingError,
    install_initial_source_bindings,
)


pytestmark = pytest.mark.no_db


@pytest.fixture
def binding_context():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    identity = IdentityContext(
        subject_id="user:admin", tenant_id="tenant", org_id="org", workspace_id="workspace",
        roles=("analyst_admin",), groups=(), data_scopes=("workspace:all",), auth_strength="test",
        issued_at=datetime.now(UTC), request_id="binding-test",
    )
    with factory() as db:
        yield db, identity
    engine.dispose()


def test_initial_source_bindings_are_versioned_approved_active_and_audited(binding_context):
    db, identity = binding_context
    installed = install_initial_source_bindings(db, identity)
    registry = SQLBotSourceBindingRegistry(db, identity)
    charging = registry.active("charging_ops")
    sales = registry.active("sales_ops")
    assert set(installed) == {"charging_ops", "sales_ops"}
    assert (charging.datasource_id, charging.status, charging.approved_by) == ("1", "ACTIVE", "user:admin")
    assert (sales.datasource_id, sales.status, sales.approved_by) == ("2", "ACTIVE", "user:admin")
    assert len(db.scalars(select(MemoryAuditEvent).where(MemoryAuditEvent.action.like("sqlbot.binding.%"))).all()) == 6


def test_source_binding_rollback_creates_new_active_version(binding_context):
    db, identity = binding_context
    registry = SQLBotSourceBindingRegistry(db, identity)
    first = registry.register(scenario_id="charging_ops", datasource_id="1", run_id="bind-1")
    registry.approve(first.binding_release_id)
    registry.activate(first.binding_release_id)
    second = registry.register(scenario_id="charging_ops", datasource_id="1", run_id="bind-2")
    registry.approve(second.binding_release_id)
    registry.activate(second.binding_release_id)
    rolled_back = registry.rollback(
        scenario_id="charging_ops",
        target_binding_release_id=first.binding_release_id,
        run_id="bind-rb",
    )
    assert rolled_back.status == "ACTIVE"
    assert rolled_back.version == 3
    assert rolled_back.rollback_of_id == second.binding_release_id
    assert registry.active("charging_ops").binding_release_id == rolled_back.binding_release_id


def test_unapproved_or_mismatched_source_binding_never_activates(binding_context):
    db, identity = binding_context
    registry = SQLBotSourceBindingRegistry(db, identity)
    draft = registry.register(scenario_id="sales_ops", datasource_id="2", run_id="bind-draft")
    with pytest.raises(SourceBindingError) as unapproved:
        registry.activate(draft.binding_release_id)
    assert unapproved.value.code == "BINDING_NOT_APPROVED"
    with pytest.raises(SourceBindingError) as mismatch:
        registry.register(scenario_id="sales_ops", datasource_id="1", run_id="bind-wrong")
    assert mismatch.value.code == "BINDING_NOT_ALLOWLISTED"
