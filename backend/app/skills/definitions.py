from __future__ import annotations

from app.memory.contracts import ProcedureStatus
from app.memory.procedural import ProcedureRegistry, ProcedureSpec, SkillRegistry, SkillSpec
from app.platform.identity import IdentityContext
from sqlalchemy.orm import Session


SKILL_CASE_COUNTS = {
    "revenue_decline_diagnosis": 10,
    "order_anomaly_analysis": 8,
    "gross_profit_change_decomposition": 8,
    "station_efficiency_diagnosis": 7,
    "operating_report_generation": 7,
}

SKILL_SCENARIOS = {
    "revenue_decline_diagnosis": ("charging_ops", "sales_ops"),
    "order_anomaly_analysis": ("charging_ops", "sales_ops"),
    "gross_profit_change_decomposition": ("charging_ops", "sales_ops"),
    "station_efficiency_diagnosis": ("charging_ops",),
    "operating_report_generation": ("charging_ops",),
}

COMMON_OUTPUT_REQUIRED = [
    "conclusion",
    "metric_change",
    "time_comparison",
    "contribution_breakdown",
    "anomalies",
    "evidence",
    "candidate_causes",
    "recommended_actions",
    "limitations",
    "confidence",
    "run_id",
    "trace_id",
]


def _procedure_spec(skill_code: str) -> ProcedureSpec:
    steps = (
        {"code": "parse_target", "tool": "metric_registry"},
        {"code": "resolve_periods", "tool": "procedure_parameter"},
        {"code": "query_current", "tool": "deterministic_engine"},
        {"code": "query_comparison", "tool": "deterministic_engine"},
        {"code": "dimension_contribution", "tool": "analysis_adapter"},
        {"code": "detect_anomaly", "tool": "deterministic_rule"},
        {"code": "retrieve_definition", "tool": "metric_registry"},
        {"code": "validate_reconciliation", "tool": "deterministic_rule"},
        {"code": "compose_recommendation", "tool": "evidence_template"},
        {"code": "write_episode", "tool": "episodic_memory"},
    )
    return ProcedureSpec(
        procedure_code=skill_code,
        version="1.0.0",
        scenario_id=None,
        owner_subject_id="role:metric_owner",
        input_schema={
            "type": "object",
            "required": ["scenario_id", "start", "end_exclusive"],
        },
        output_schema={"type": "object", "required": COMMON_OUTPUT_REQUIRED},
        steps=steps,
        branches=(
            {"when": "comparison=yoy", "then": "year_over_year"},
            {"when": "comparison=mom", "then": "previous_period"},
        ),
        validations=(
            {"code": "metric_registry_authorized"},
            {"code": "contribution_reconciled"},
            {"code": "evidence_required"},
            {"code": "causality_boundary"},
        ),
        failure_policy={
            "on_tool_error": "fail_closed",
            "write_success_episode_on_failure": False,
        },
        test_manifest={"passed": True, "case_count": SKILL_CASE_COUNTS[skill_code]},
        rollout={"strategy": "approved_release", "rollback": "previous_version"},
    )


def install_initial_skills(db: Session, identity: IdentityContext) -> dict:
    if "analyst_admin" not in identity.roles:
        raise PermissionError("initial skill installation requires analyst_admin")
    installed = []
    for skill_code, scenarios in SKILL_SCENARIOS.items():
        procedure_registry = ProcedureRegistry(db, identity)
        procedure = procedure_registry.register(_procedure_spec(skill_code))
        if procedure.status in {ProcedureStatus.DRAFT, ProcedureStatus.CANDIDATE}:
            procedure_registry.submit_review(procedure.procedure_id)
        if procedure.status == ProcedureStatus.REVIEWING:
            procedure_registry.approve(procedure.procedure_id)
        if procedure.status in {
            ProcedureStatus.APPROVED,
            ProcedureStatus.SHADOW,
            ProcedureStatus.CANARY,
        }:
            procedure_registry.activate(procedure.procedure_id)
        for scenario_id in scenarios:
            registry = SkillRegistry(db, identity)
            skill = registry.register(SkillSpec(
                skill_code=skill_code,
                version="1.0.0",
                scenario_id=scenario_id,
                procedure_id=procedure.procedure_id,
                owner_subject_id="role:metric_owner",
                adapter_code="registry_driven_analysis",
                input_schema={
                    "type": "object",
                    "required": ["start", "end_exclusive", "comparison"],
                },
                output_schema={"type": "object", "required": COMMON_OUTPUT_REQUIRED},
            ))
            if skill.status in {ProcedureStatus.DRAFT, ProcedureStatus.CANDIDATE}:
                registry.submit_review(skill.skill_id)
            if skill.status == ProcedureStatus.REVIEWING:
                registry.approve(skill.skill_id)
            if skill.status in {
                ProcedureStatus.APPROVED,
                ProcedureStatus.SHADOW,
                ProcedureStatus.CANARY,
            }:
                registry.activate(skill.skill_id)
            installed.append({
                "skill_id": skill.skill_id,
                "skill_code": skill.skill_code,
                "scenario_id": skill.scenario_id,
                "version": skill.version,
                "status": skill.status,
                "enabled": skill.enabled,
            })
    return {"installed": installed, "skill_count": len(installed)}
