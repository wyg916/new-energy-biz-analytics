from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import current_user, require_roles
from app.core.database import get_db
from app.memory.models import ProcedureDefinition, SkillDefinition
from app.memory.procedural import ProcedureRegistryError, SkillRegistry
from app.models.auth import User
from app.orchestration.memory_skills import MemorySkillOrchestrator
from app.platform.identity import IdentityContextFactory
from app.skills.contracts import SkillRequest
from app.skills.definitions import install_initial_skills
from app.skills.runtime import SkillExecutionError


router = APIRouter(prefix="/skills", tags=["skills"])


def _skill_view(
    row: SkillDefinition,
    procedure: ProcedureDefinition | None,
    *,
    can_administer: bool = False,
) -> dict:
    return {
        "skill_id": row.skill_id,
        "skill_code": row.skill_code,
        "scenario_id": row.scenario_id,
        "version": row.version,
        "status": row.status,
        "owner": row.owner_subject_id,
        "enabled": row.enabled,
        "input_schema": json.loads(row.input_schema_json),
        "output_schema": json.loads(row.output_schema_json),
        "adapter_code": row.adapter_code,
        "steps": json.loads(procedure.steps_json) if procedure else [],
        "validations": json.loads(procedure.validations_json) if procedure else [],
        "shadow_result": json.loads(row.shadow_result_json),
        "rollback_skill_id": row.rollback_skill_id,
        "approved_by": row.approved_by,
        "approved_at": row.approved_at,
        "controls": {
            "can_enable": can_administer and row.status in {"APPROVED", "SHADOW", "CANARY"},
            "can_disable": can_administer and row.status == "ACTIVE" and row.enabled,
            "can_rollback": can_administer and bool(row.rollback_skill_id),
        },
    }


@router.get("")
def list_skills(
    scenario_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    query = select(SkillDefinition).order_by(
        SkillDefinition.skill_code, SkillDefinition.scenario_id, SkillDefinition.version.desc()
    )
    if scenario_id:
        query = query.where(SkillDefinition.scenario_id == scenario_id)
    rows = db.scalars(query).all()
    can_administer = user.role == "analyst_admin"
    return {
        "skills": [
            _skill_view(
                row,
                db.get(ProcedureDefinition, row.procedure_id),
                can_administer=can_administer,
            )
            for row in rows
        ],
        "data_classification": "simulated",
    }


@router.post("/execute")
def execute_skill(
    payload: SkillRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    try:
        return MemorySkillOrchestrator(db, user).execute(payload)
    except (SkillExecutionError, ValueError) as exc:
        code = getattr(exc, "code", "SKILL_EXECUTION_FAILED")
        raise HTTPException(422, detail={"code": code, "message": str(exc)}) from exc
    except LookupError as exc:
        raise HTTPException(409, detail={"code": str(exc), "message": "Skill 未启用"}) from exc


@router.post("/install-initial")
def install_skills(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("analyst_admin")),
) -> dict:
    return install_initial_skills(db, IdentityContextFactory.from_user(user))


@router.post("/{skill_id}/enable")
def enable_skill(
    skill_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("analyst_admin")),
) -> dict:
    try:
        row = SkillRegistry(db, IdentityContextFactory.from_user(user)).activate(skill_id)
        return _skill_view(
            row,
            db.get(ProcedureDefinition, row.procedure_id),
            can_administer=True,
        )
    except ProcedureRegistryError as exc:
        raise HTTPException(409, detail={"code": exc.code, "message": exc.message}) from exc


@router.post("/{skill_id}/disable")
def disable_skill(
    skill_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("analyst_admin")),
) -> dict:
    try:
        row = SkillRegistry(db, IdentityContextFactory.from_user(user)).disable(skill_id)
        return _skill_view(
            row,
            db.get(ProcedureDefinition, row.procedure_id),
            can_administer=True,
        )
    except ProcedureRegistryError as exc:
        raise HTTPException(409, detail={"code": exc.code, "message": exc.message}) from exc


@router.post("/{skill_id}/rollback")
def rollback_skill(
    skill_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("analyst_admin")),
) -> dict:
    try:
        row = SkillRegistry(db, IdentityContextFactory.from_user(user)).rollback(skill_id)
        return _skill_view(
            row,
            db.get(ProcedureDefinition, row.procedure_id),
            can_administer=True,
        )
    except ProcedureRegistryError as exc:
        raise HTTPException(409, detail={"code": exc.code, "message": exc.message}) from exc
