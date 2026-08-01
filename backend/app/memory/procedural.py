from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session

from app.memory.audit import audit_memory_use
from app.memory.contracts import ProcedureStatus
from app.memory.models import ProcedureDefinition, SkillDefinition
from app.platform.identity import IdentityContext


class ProcedureRegistryError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ProcedureSpec:
    procedure_code: str
    version: str
    scenario_id: str | None
    owner_subject_id: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    steps: tuple[dict[str, Any], ...]
    branches: tuple[dict[str, Any], ...]
    validations: tuple[dict[str, Any], ...]
    failure_policy: dict[str, Any]
    test_manifest: dict[str, Any]
    rollout: dict[str, Any] = field(default_factory=dict)
    rollback_procedure_id: str | None = None


@dataclass(frozen=True)
class SkillSpec:
    skill_code: str
    version: str
    scenario_id: str
    procedure_id: str
    owner_subject_id: str
    adapter_code: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    rollback_skill_id: str | None = None


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _require_reviewer(identity: IdentityContext) -> None:
    if "analyst_admin" not in identity.roles:
        raise ProcedureRegistryError("HUMAN_REVIEW_REQUIRED", "仅管理员可审核或发布程序规则")


class ProcedureRegistry:
    def __init__(self, db: Session, identity: IdentityContext) -> None:
        self.db = db
        self.identity = identity

    def register(
        self,
        spec: ProcedureSpec,
        *,
        generated_by_reflection: bool = False,
    ) -> ProcedureDefinition:
        existing = self.db.scalar(select(ProcedureDefinition).where(
            ProcedureDefinition.procedure_code == spec.procedure_code,
            ProcedureDefinition.version == spec.version,
        ))
        payload = {
            "input_schema_json": _json(spec.input_schema),
            "output_schema_json": _json(spec.output_schema),
            "steps_json": _json(spec.steps),
            "branches_json": _json(spec.branches),
            "validations_json": _json(spec.validations),
            "failure_policy_json": _json(spec.failure_policy),
            "test_manifest_json": _json(spec.test_manifest),
            "rollout_json": _json(spec.rollout),
        }
        if existing:
            if any(getattr(existing, key) != value for key, value in payload.items()):
                raise ProcedureRegistryError(
                    "IMMUTABLE_PROCEDURE_VERSION",
                    "相同版本的程序定义不可原地修改，请创建新版本",
                )
            return existing
        if not spec.steps or not spec.validations:
            raise ProcedureRegistryError(
                "INCOMPLETE_PROCEDURE",
                "程序定义必须包含步骤和校验规则",
            )
        status = ProcedureStatus.CANDIDATE if generated_by_reflection else ProcedureStatus.DRAFT
        definition = ProcedureDefinition(
            procedure_id=f"PROC-{uuid4()}",
            procedure_code=spec.procedure_code,
            version=spec.version,
            scenario_id=spec.scenario_id,
            status=status,
            owner_subject_id=spec.owner_subject_id,
            rollback_procedure_id=spec.rollback_procedure_id,
            **payload,
        )
        self.db.add(definition)
        audit_memory_use(
            self.db,
            self.identity,
            action="procedure.register",
            outcome=status.lower(),
            detail={
                "procedure_id": definition.procedure_id,
                "procedure_code": spec.procedure_code,
                "version": spec.version,
                "reflection": generated_by_reflection,
            },
        )
        self.db.commit()
        return definition

    def submit_review(self, procedure_id: str) -> ProcedureDefinition:
        definition = self._get(procedure_id)
        if definition.status not in {ProcedureStatus.DRAFT, ProcedureStatus.CANDIDATE}:
            raise ProcedureRegistryError("INVALID_PROCEDURE_TRANSITION", "当前状态不能提交审核")
        definition.status = ProcedureStatus.REVIEWING
        self._audit(definition, "procedure.submit_review", "success")
        self.db.commit()
        return definition

    def approve(self, procedure_id: str) -> ProcedureDefinition:
        _require_reviewer(self.identity)
        definition = self._get(procedure_id)
        if definition.status != ProcedureStatus.REVIEWING:
            raise ProcedureRegistryError("INVALID_PROCEDURE_TRANSITION", "仅审核中的程序可批准")
        tests = json.loads(definition.test_manifest_json)
        if not tests.get("passed") or int(tests.get("case_count", 0)) <= 0:
            raise ProcedureRegistryError("PROCEDURE_TESTS_NOT_PASSED", "程序测试未通过")
        definition.status = ProcedureStatus.APPROVED
        definition.approved_by = self.identity.subject_id
        definition.approved_at = datetime.now(UTC)
        self._audit(definition, "procedure.approve", "success")
        self.db.commit()
        return definition

    def activate(self, procedure_id: str, *, rollout_status: ProcedureStatus = ProcedureStatus.ACTIVE) -> ProcedureDefinition:
        _require_reviewer(self.identity)
        if rollout_status not in {
            ProcedureStatus.SHADOW,
            ProcedureStatus.CANARY,
            ProcedureStatus.ACTIVE,
        }:
            raise ProcedureRegistryError("INVALID_ROLLOUT_STATUS", "程序发布状态不合法")
        definition = self._get(procedure_id)
        if definition.status not in {
            ProcedureStatus.APPROVED,
            ProcedureStatus.SHADOW,
            ProcedureStatus.CANARY,
        }:
            raise ProcedureRegistryError("PROCEDURE_NOT_APPROVED", "未经批准的程序不能生效")
        if not definition.approved_by:
            raise ProcedureRegistryError("PROCEDURE_NOT_APPROVED", "缺少人工批准记录")
        definition.status = rollout_status
        self._audit(definition, "procedure.activate", "success", {"status": rollout_status})
        self.db.commit()
        return definition

    def deprecate(self, procedure_id: str) -> ProcedureDefinition:
        _require_reviewer(self.identity)
        definition = self._get(procedure_id)
        if definition.status not in {
            ProcedureStatus.SHADOW,
            ProcedureStatus.CANARY,
            ProcedureStatus.ACTIVE,
        }:
            raise ProcedureRegistryError("INVALID_PROCEDURE_TRANSITION", "当前状态不能停用")
        definition.status = ProcedureStatus.DEPRECATED
        self._audit(definition, "procedure.deprecate", "success")
        self.db.commit()
        return definition

    def rollback(self, procedure_id: str) -> ProcedureDefinition:
        _require_reviewer(self.identity)
        current = self._get(procedure_id)
        if not current.rollback_procedure_id:
            raise ProcedureRegistryError("ROLLBACK_TARGET_MISSING", "Procedure 未配置回滚版本")
        target = self._get(current.rollback_procedure_id)
        if not target.approved_by or target.status not in {
            ProcedureStatus.APPROVED,
            ProcedureStatus.DEPRECATED,
            ProcedureStatus.ACTIVE,
        }:
            raise ProcedureRegistryError("ROLLBACK_TARGET_NOT_APPROVED", "回滚目标未经批准")
        current.status = ProcedureStatus.DEPRECATED
        target.status = ProcedureStatus.ACTIVE
        self._audit(
            current,
            "procedure.rollback",
            "success",
            {"rollback_target_procedure_id": target.procedure_id},
        )
        self.db.commit()
        return target

    def match(self, *, procedure_code: str, scenario_id: str) -> ProcedureDefinition | None:
        return self.db.scalar(select(ProcedureDefinition).where(
            ProcedureDefinition.procedure_code == procedure_code,
            ProcedureDefinition.status == ProcedureStatus.ACTIVE,
            or_(
                ProcedureDefinition.scenario_id == scenario_id,
                ProcedureDefinition.scenario_id.is_(None),
            ),
            ProcedureDefinition.approved_by.is_not(None),
        ).order_by(
            desc(ProcedureDefinition.scenario_id),
            desc(ProcedureDefinition.version),
        ))

    def _get(self, procedure_id: str) -> ProcedureDefinition:
        definition = self.db.get(ProcedureDefinition, procedure_id)
        if definition is None:
            raise ProcedureRegistryError("PROCEDURE_NOT_FOUND", "程序定义不存在")
        return definition

    def _audit(
        self,
        definition: ProcedureDefinition,
        action: str,
        outcome: str,
        detail: dict | None = None,
    ) -> None:
        audit_memory_use(
            self.db,
            self.identity,
            action=action,
            outcome=outcome,
            detail={
                "procedure_id": definition.procedure_id,
                "procedure_code": definition.procedure_code,
                **(detail or {}),
            },
        )


class SkillRegistry:
    def __init__(self, db: Session, identity: IdentityContext) -> None:
        self.db = db
        self.identity = identity

    def register(self, spec: SkillSpec) -> SkillDefinition:
        procedure = self.db.get(ProcedureDefinition, spec.procedure_id)
        if procedure is None:
            raise ProcedureRegistryError("PROCEDURE_NOT_FOUND", "Skill 引用的程序不存在")
        if procedure.scenario_id not in {None, spec.scenario_id}:
            raise ProcedureRegistryError("PROCEDURE_SCENARIO_MISMATCH", "Skill 与程序场景不匹配")
        existing = self.db.scalar(select(SkillDefinition).where(
            SkillDefinition.skill_code == spec.skill_code,
            SkillDefinition.version == spec.version,
            SkillDefinition.scenario_id == spec.scenario_id,
        ))
        payload = {
            "procedure_id": spec.procedure_id,
            "adapter_code": spec.adapter_code,
            "input_schema_json": _json(spec.input_schema),
            "output_schema_json": _json(spec.output_schema),
        }
        if existing:
            if any(getattr(existing, key) != value for key, value in payload.items()):
                raise ProcedureRegistryError(
                    "IMMUTABLE_SKILL_VERSION",
                    "相同版本的 Skill 不可原地修改，请创建新版本",
                )
            return existing
        definition = SkillDefinition(
            skill_id=f"SKILL-{uuid4()}",
            skill_code=spec.skill_code,
            version=spec.version,
            scenario_id=spec.scenario_id,
            status=ProcedureStatus.DRAFT,
            owner_subject_id=spec.owner_subject_id,
            rollback_skill_id=spec.rollback_skill_id,
            enabled=False,
            **payload,
        )
        self.db.add(definition)
        self._audit(definition, "skill.register", "draft")
        self.db.commit()
        return definition

    def submit_review(self, skill_id: str) -> SkillDefinition:
        definition = self._get(skill_id)
        if definition.status not in {ProcedureStatus.DRAFT, ProcedureStatus.CANDIDATE}:
            raise ProcedureRegistryError("INVALID_SKILL_TRANSITION", "当前 Skill 状态不能提交审核")
        definition.status = ProcedureStatus.REVIEWING
        self._audit(definition, "skill.submit_review", "success")
        self.db.commit()
        return definition

    def approve(self, skill_id: str) -> SkillDefinition:
        _require_reviewer(self.identity)
        definition = self._get(skill_id)
        procedure = self.db.get(ProcedureDefinition, definition.procedure_id)
        if definition.status != ProcedureStatus.REVIEWING:
            raise ProcedureRegistryError("INVALID_SKILL_TRANSITION", "仅审核中的 Skill 可批准")
        if procedure is None or procedure.status not in {
            ProcedureStatus.APPROVED,
            ProcedureStatus.SHADOW,
            ProcedureStatus.CANARY,
            ProcedureStatus.ACTIVE,
        }:
            raise ProcedureRegistryError("PROCEDURE_NOT_APPROVED", "Skill 的程序尚未批准")
        definition.status = ProcedureStatus.APPROVED
        definition.approved_by = self.identity.subject_id
        definition.approved_at = datetime.now(UTC)
        self._audit(definition, "skill.approve", "success")
        self.db.commit()
        return definition

    def activate(self, skill_id: str, *, rollout_status: ProcedureStatus = ProcedureStatus.ACTIVE) -> SkillDefinition:
        _require_reviewer(self.identity)
        if rollout_status not in {
            ProcedureStatus.SHADOW,
            ProcedureStatus.CANARY,
            ProcedureStatus.ACTIVE,
        }:
            raise ProcedureRegistryError("INVALID_ROLLOUT_STATUS", "Skill 发布状态不合法")
        definition = self._get(skill_id)
        procedure = self.db.get(ProcedureDefinition, definition.procedure_id)
        if definition.status not in {
            ProcedureStatus.APPROVED,
            ProcedureStatus.SHADOW,
            ProcedureStatus.CANARY,
        } or not definition.approved_by:
            raise ProcedureRegistryError("SKILL_NOT_APPROVED", "未经批准的 Skill 不能启用")
        if procedure is None or procedure.status != ProcedureStatus.ACTIVE:
            raise ProcedureRegistryError("PROCEDURE_NOT_ACTIVE", "Skill 的程序尚未 ACTIVE")
        definition.status = rollout_status
        definition.enabled = rollout_status is ProcedureStatus.ACTIVE
        self._audit(definition, "skill.activate", "success", {"status": rollout_status})
        self.db.commit()
        return definition

    def disable(self, skill_id: str) -> SkillDefinition:
        _require_reviewer(self.identity)
        definition = self._get(skill_id)
        definition.enabled = False
        definition.status = ProcedureStatus.DEPRECATED
        self._audit(definition, "skill.disable", "success")
        self.db.commit()
        return definition

    def rollback(self, skill_id: str) -> SkillDefinition:
        _require_reviewer(self.identity)
        current = self._get(skill_id)
        if not current.rollback_skill_id:
            raise ProcedureRegistryError("ROLLBACK_TARGET_MISSING", "Skill 未配置回滚版本")
        target = self._get(current.rollback_skill_id)
        if not target.approved_by:
            raise ProcedureRegistryError("ROLLBACK_TARGET_NOT_APPROVED", "回滚目标未经批准")
        procedure = self.db.get(ProcedureDefinition, target.procedure_id)
        if procedure is None or procedure.status != ProcedureStatus.ACTIVE:
            raise ProcedureRegistryError("PROCEDURE_NOT_ACTIVE", "回滚目标程序未生效")
        current.enabled = False
        current.status = ProcedureStatus.DEPRECATED
        target.enabled = True
        target.status = ProcedureStatus.ACTIVE
        self._audit(
            current,
            "skill.rollback",
            "success",
            {"rollback_target_skill_id": target.skill_id},
        )
        self.db.commit()
        return target

    def match(self, *, skill_code: str, scenario_id: str) -> SkillDefinition | None:
        return self.db.scalar(select(SkillDefinition).where(
            SkillDefinition.skill_code == skill_code,
            SkillDefinition.scenario_id == scenario_id,
            SkillDefinition.status == ProcedureStatus.ACTIVE,
            SkillDefinition.enabled.is_(True),
            SkillDefinition.approved_by.is_not(None),
        ).order_by(desc(SkillDefinition.version)))

    def list_for_scenario(self, scenario_id: str) -> list[SkillDefinition]:
        return list(self.db.scalars(select(SkillDefinition).where(
            SkillDefinition.scenario_id == scenario_id,
        ).order_by(SkillDefinition.skill_code, desc(SkillDefinition.version))).all())

    def _get(self, skill_id: str) -> SkillDefinition:
        definition = self.db.get(SkillDefinition, skill_id)
        if definition is None:
            raise ProcedureRegistryError("SKILL_NOT_FOUND", "Skill 不存在")
        return definition

    def _audit(
        self,
        definition: SkillDefinition,
        action: str,
        outcome: str,
        detail: dict | None = None,
    ) -> None:
        audit_memory_use(
            self.db,
            self.identity,
            action=action,
            outcome=outcome,
            detail={
                "skill_id": definition.skill_id,
                "skill_code": definition.skill_code,
                "scenario_id": definition.scenario_id,
                **(detail or {}),
            },
        )
