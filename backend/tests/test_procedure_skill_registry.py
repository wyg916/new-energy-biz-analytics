import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.memory.contracts import ProcedureStatus
from app.memory.models import P2B_MEMORY_TABLES
from app.memory.procedural import (
    ProcedureRegistry,
    ProcedureRegistryError,
    ProcedureSpec,
    SkillRegistry,
    SkillSpec,
)
from app.models.auth import User
from app.platform.identity import IdentityContextFactory


pytestmark = pytest.mark.no_db


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    for table in P2B_MEMORY_TABLES:
        table.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session
    engine.dispose()


def identity(*, admin=False):
    user = User(
        id=1 if not admin else 2,
        username="admin" if admin else "analyst",
        password_hash="x",
        display_name="Reviewer" if admin else "Analyst",
        role="analyst_admin" if admin else "analyst",
        region_code=None,
        is_active=True,
    )
    return IdentityContextFactory.from_user(user)


def procedure_spec(*, code="revenue_decline_diagnosis", version="1.0.0", scenario=None, passed=True):
    return ProcedureSpec(
        procedure_code=code,
        version=version,
        scenario_id=scenario,
        owner_subject_id="role:metric_owner",
        input_schema={"type": "object", "required": ["metric", "time_range"]},
        output_schema={"type": "object", "required": ["conclusion", "evidence"]},
        steps=(
            {"code": "parse_metric", "tool": "metric_registry"},
            {"code": "query_trend", "tool": "deterministic_engine"},
        ),
        branches=({"when": "comparison=yoy", "then": "year_over_year"},),
        validations=({"code": "evidence_required"},),
        failure_policy={"on_tool_error": "fail_closed"},
        test_manifest={"passed": passed, "case_count": 10},
        rollout={"shadow_percentage": 100},
    )


def skill_spec(procedure_id, *, code="revenue_decline_diagnosis", version="1.0.0", scenario="charging_ops", rollback=None):
    return SkillSpec(
        skill_code=code,
        version=version,
        scenario_id=scenario,
        procedure_id=procedure_id,
        owner_subject_id="role:metric_owner",
        adapter_code="registry_driven_analysis",
        input_schema={"type": "object"},
        output_schema={"type": "object", "required": ["run_id", "trace_id"]},
        rollback_skill_id=rollback,
    )


def approve_procedure(db):
    created = ProcedureRegistry(db, identity()).register(procedure_spec())
    ProcedureRegistry(db, identity()).submit_review(created.procedure_id)
    approved = ProcedureRegistry(db, identity(admin=True)).approve(created.procedure_id)
    return ProcedureRegistry(db, identity(admin=True)).activate(approved.procedure_id)


def test_reflection_only_creates_candidate(db):
    definition = ProcedureRegistry(db, identity()).register(
        procedure_spec(), generated_by_reflection=True
    )
    assert definition.status == ProcedureStatus.CANDIDATE
    assert ProcedureRegistry(db, identity()).match(
        procedure_code=definition.procedure_code, scenario_id="charging_ops"
    ) is None


def test_procedure_version_is_immutable(db):
    registry = ProcedureRegistry(db, identity())
    registry.register(procedure_spec())
    changed = procedure_spec()
    changed = ProcedureSpec(**{**changed.__dict__, "steps": ({"code": "changed"},)})
    with pytest.raises(ProcedureRegistryError) as error:
        registry.register(changed)
    assert error.value.code == "IMMUTABLE_PROCEDURE_VERSION"


def test_non_admin_cannot_approve_procedure(db):
    definition = ProcedureRegistry(db, identity()).register(procedure_spec())
    ProcedureRegistry(db, identity()).submit_review(definition.procedure_id)
    with pytest.raises(ProcedureRegistryError) as error:
        ProcedureRegistry(db, identity()).approve(definition.procedure_id)
    assert error.value.code == "HUMAN_REVIEW_REQUIRED"


def test_failed_tests_prevent_procedure_approval(db):
    definition = ProcedureRegistry(db, identity()).register(procedure_spec(passed=False))
    ProcedureRegistry(db, identity()).submit_review(definition.procedure_id)
    with pytest.raises(ProcedureRegistryError) as error:
        ProcedureRegistry(db, identity(admin=True)).approve(definition.procedure_id)
    assert error.value.code == "PROCEDURE_TESTS_NOT_PASSED"


def test_approved_active_procedure_can_be_matched(db):
    active = approve_procedure(db)
    matched = ProcedureRegistry(db, identity()).match(
        procedure_code=active.procedure_code, scenario_id="sales_ops"
    )
    assert matched.procedure_id == active.procedure_id
    assert matched.approved_by == identity(admin=True).subject_id


def test_skill_requires_existing_procedure(db):
    with pytest.raises(ProcedureRegistryError) as error:
        SkillRegistry(db, identity()).register(skill_spec("PROC-MISSING"))
    assert error.value.code == "PROCEDURE_NOT_FOUND"


def test_skill_cannot_activate_before_human_approval(db):
    procedure = approve_procedure(db)
    skill = SkillRegistry(db, identity()).register(skill_spec(procedure.procedure_id))
    with pytest.raises(ProcedureRegistryError) as error:
        SkillRegistry(db, identity(admin=True)).activate(skill.skill_id)
    assert error.value.code == "SKILL_NOT_APPROVED"


def test_skill_full_approval_and_activation(db):
    procedure = approve_procedure(db)
    registry = SkillRegistry(db, identity())
    skill = registry.register(skill_spec(procedure.procedure_id))
    registry.submit_review(skill.skill_id)
    SkillRegistry(db, identity(admin=True)).approve(skill.skill_id)
    active = SkillRegistry(db, identity(admin=True)).activate(skill.skill_id)
    matched = SkillRegistry(db, identity()).match(
        skill_code=skill.skill_code, scenario_id="charging_ops"
    )
    assert active.enabled is True
    assert active.status == ProcedureStatus.ACTIVE
    assert matched.skill_id == skill.skill_id


def test_skill_is_scenario_isolated(db):
    procedure = approve_procedure(db)
    skill = SkillRegistry(db, identity()).register(skill_spec(procedure.procedure_id))
    SkillRegistry(db, identity()).submit_review(skill.skill_id)
    SkillRegistry(db, identity(admin=True)).approve(skill.skill_id)
    SkillRegistry(db, identity(admin=True)).activate(skill.skill_id)
    assert SkillRegistry(db, identity()).match(
        skill_code=skill.skill_code, scenario_id="sales_ops"
    ) is None


def test_skill_disable_removes_from_match(db):
    procedure = approve_procedure(db)
    skill = SkillRegistry(db, identity()).register(skill_spec(procedure.procedure_id))
    SkillRegistry(db, identity()).submit_review(skill.skill_id)
    SkillRegistry(db, identity(admin=True)).approve(skill.skill_id)
    SkillRegistry(db, identity(admin=True)).activate(skill.skill_id)
    SkillRegistry(db, identity(admin=True)).disable(skill.skill_id)
    assert SkillRegistry(db, identity()).match(
        skill_code=skill.skill_code, scenario_id="charging_ops"
    ) is None


def test_skill_rollback_reactivates_approved_target(db):
    procedure = approve_procedure(db)
    registry = SkillRegistry(db, identity())
    v1 = registry.register(skill_spec(procedure.procedure_id, version="1.0.0"))
    registry.submit_review(v1.skill_id)
    SkillRegistry(db, identity(admin=True)).approve(v1.skill_id)
    SkillRegistry(db, identity(admin=True)).activate(v1.skill_id)
    SkillRegistry(db, identity(admin=True)).disable(v1.skill_id)
    v2 = registry.register(skill_spec(
        procedure.procedure_id,
        version="2.0.0",
        rollback=v1.skill_id,
    ))
    registry.submit_review(v2.skill_id)
    SkillRegistry(db, identity(admin=True)).approve(v2.skill_id)
    SkillRegistry(db, identity(admin=True)).activate(v2.skill_id)
    rolled_back = SkillRegistry(db, identity(admin=True)).rollback(v2.skill_id)
    assert rolled_back.skill_id == v1.skill_id
    assert rolled_back.enabled is True
    assert v2.status == ProcedureStatus.DEPRECATED


@pytest.mark.parametrize(
    "status",
    [ProcedureStatus.DRAFT, ProcedureStatus.CANDIDATE, ProcedureStatus.REVIEWING, ProcedureStatus.FAILED],
)
def test_unapproved_procedure_never_matches(db, status):
    definition = ProcedureRegistry(db, identity()).register(
        procedure_spec(code=f"procedure_{status.lower()}")
    )
    definition.status = status
    db.commit()
    assert ProcedureRegistry(db, identity()).match(
        procedure_code=definition.procedure_code,
        scenario_id="charging_ops",
    ) is None
