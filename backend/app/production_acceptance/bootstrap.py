from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.production_acceptance.models import ProductionGate


BASELINE_GATES: tuple[dict[str, object], ...] = (
    {
        "code": "REMOTE_PUSH", "title": "Git 远端分发完整性", "category": "delivery",
        "owner": "release_owner", "blocker": "BLOCKER", "external": False, "status": "BLOCKED",
        "review": "远端分支 SHA 必须等于本地冻结 SHA，ahead/behind 为 0/0，并在代码变更后复核。",
    },
    {
        "code": "DOCKER_RUNTIME", "title": "Docker/WSL 标准运行环境", "category": "runtime",
        "owner": "operations_owner", "blocker": "BLOCKER", "external": False, "status": "BLOCKED",
        "review": "独立 P5A Compose 的运行服务、一次性任务、网络、卷、liveness 与 readiness 均须有本轮证据。",
    },
    {
        "code": "POSTGRES_CANONICAL_REGRESSION", "title": "PostgreSQL 权威业务回归", "category": "data",
        "owner": "data_owner", "blocker": "BLOCKER", "external": False, "status": "BLOCKED",
        "review": "固定数据规模、15+12 指标、DQ 与固定评测必须在 PostgreSQL 标准环境全部通过。",
    },
    {
        "code": "FRONTEND_E2E", "title": "完整浏览器关键路径", "category": "quality",
        "owner": "quality_owner", "blocker": "BLOCKER", "external": False, "status": "BLOCKED",
        "review": "冻结 Playwright 26 条与 P5 门禁路径 1 条必须使用正式 API、PostgreSQL 和真实 Keycloak 通过。",
    },
    {
        "code": "IMAGE_SECURITY", "title": "全部容器镜像安全签署", "category": "security",
        "owner": "security_owner", "blocker": "BLOCKER", "external": False, "status": "BLOCKED",
        "review": "全部运行与禁用镜像实际复扫；Critical=0，High=0 或逐项正式例外。",
    },
    {
        "code": "KEYCLOAK_SECURITY", "title": "Keycloak 镜像安全", "category": "security",
        "owner": "security_owner", "blocker": "BLOCKER", "external": False, "status": "BLOCKED",
        "review": "实际镜像 Critical=0 且 High=0，或每项均有权威不适用证据或正式 waiver。",
    },
    {
        "code": "VAULT_SECURITY", "title": "Vault 镜像安全", "category": "security",
        "owner": "security_owner", "blocker": "BLOCKER", "external": False, "status": "BLOCKED",
        "review": "实际镜像 Critical=0 且 High=0，或每项均有权威不适用证据或正式 waiver。",
    },
    {
        "code": "SQLBOT_IMAGE_SECURITY", "title": "SQLBot 固定摘要镜像安全", "category": "security",
        "owner": "security_owner", "blocker": "BLOCKER", "external": False, "status": "BLOCKED",
        "review": "禁用镜像仍须按固定 digest 完成实际扫描；扫描不代表启用或 Canary 资格。",
    },
    {
        "code": "CAPACITY_SOAK", "title": "P5A 两小时容量耐久", "category": "capacity",
        "owner": "operations_owner", "blocker": "BLOCKER", "external": False, "status": "BLOCKED",
        "review": "100 逻辑用户、并发 20、7200 秒，错误、超时、资源、连接、审计和重启证据完整。",
    },
    {
        "code": "BACKUP_RECOVERY", "title": "P5A 故障备份恢复", "category": "resilience",
        "owner": "operations_owner", "blocker": "BLOCKER", "external": False, "status": "BLOCKED",
        "review": "故障、完整备份、临时库恢复、数据哈希、门禁历史和迁移循环均使用本轮证据。",
    },
    {
        "code": "ENTERPRISE_IDP", "title": "真实企业 IdP 联调", "category": "identity",
        "owner": "identity_owner", "blocker": "BLOCKER", "external": True, "status": "OPEN",
        "review": "企业测试租户、metadata、claims、禁用、撤权、JWKS 轮换和回滚均有真实证据。",
    },
    {
        "code": "PRODUCTION_SECRET_MANAGER", "title": "托管生产 Secret Manager", "category": "secrets",
        "owner": "security_owner", "blocker": "BLOCKER", "external": True, "status": "OPEN",
        "review": "需用户授权的托管实例、HA、备份、CredentialReference、轮换及 fail-closed 证据。",
    },
    {
        "code": "SECRET_MANAGER", "title": "生产 Secret Manager", "category": "secrets",
        "owner": "security_owner", "blocker": "BLOCKER", "external": True, "status": "OPEN",
        "review": "生产托管实例、HA、备份、CredentialReference、轮换和 fail-closed 有授权证据。",
    },
    {
        "code": "SQLBOT_EXTERNAL_REVIEW", "title": "SQLBot 外部 10/30/20 安全复评", "category": "sqlbot",
        "owner": "ai_platform_owner", "blocker": "BLOCKER", "external": True, "status": "OPEN",
        "review": "仅在授权 CredentialReference 注入后按顺序执行，安全违规必须为 0。",
    },
    {
        "code": "SQLBOT_EXTERNAL_RUNTIME", "title": "SQLBot 外部模型运行时", "category": "sqlbot",
        "owner": "ai_platform_owner", "blocker": "BLOCKER", "external": True, "status": "OPEN",
        "review": "需用户提供授权 CredentialReference；未授权时 SQLBot 保持 disabled 且不得执行 Canary。",
    },
    {
        "code": "RAG_MODE", "title": "RAG 正式运行模式", "category": "rag",
        "owner": "knowledge_owner", "blocker": "BLOCKER", "external": False, "status": "PASSED",
        "review": "明确发布 Vector 或冻结 keyword-only，UI、API、文档和 Manifest 一致。",
        "evidence": [{
            "evidence_type": "manifest",
            "uri": "docs/platformization/p5/evidence/rag-keyword-release.json",
            "sha256": "a59c871188aba4216a82281790a7bb1e3064ed0dc28f83e11fff144e35eccd8e",
            "observed_at": "2026-08-02T05:50:00+00:00",
            "summary": "P5 formally freezes keyword-only RAG and defers vector release.",
        }],
    },
    {
        "code": "PRODUCTION_DATA_APPROVAL", "title": "生产数据接入审批", "category": "data",
        "owner": "data_owner", "blocker": "BLOCKER", "external": True, "status": "OPEN",
        "review": "数据分类、脱敏、最小权限、只读、保留、删除、审计和断开连接全部获批。",
    },
    {
        "code": "PRODUCTION_DATA", "title": "真实生产数据接入", "category": "data",
        "owner": "data_owner", "blocker": "BLOCKER", "external": True, "status": "OPEN",
        "review": "需真实授权、分类、脱敏、最小只读权限、保留删除、审计和断开连接证据。",
    },
    {
        "code": "PRODUCTION_CAPACITY", "title": "代表性生产容量与 SLA", "category": "capacity",
        "owner": "operations_owner", "blocker": "BLOCKER", "external": True, "status": "OPEN",
        "review": "提供生产同构规格并完成容量、耐久、故障和备份期间影响验收；本地值不替代 SLA。",
    },
    {
        "code": "BACKUP_RESTORE", "title": "备份恢复复验", "category": "resilience",
        "owner": "operations_owner", "blocker": "BLOCKER", "external": False, "status": "OPEN",
        "review": "P5 head 下完成源/恢复摘要、业务哈希、Secret 边界和源卷保留复验。",
    },
    {
        "code": "MONITORING_ALERTING", "title": "企业监控告警联调", "category": "observability",
        "owner": "operations_owner", "blocker": "BLOCKER", "external": True, "status": "OPEN",
        "review": "授权接收端完成签名、重试、幂等、熔断、超时、脱敏、限流和恢复验收。",
    },
    {
        "code": "ENTERPRISE_ALERT", "title": "企业告警接收端", "category": "observability",
        "owner": "operations_owner", "blocker": "BLOCKER", "external": True, "status": "OPEN",
        "review": "需授权企业接收端的签名、重试、幂等、熔断、超时、脱敏、限流和恢复证据。",
    },
    {
        "code": "CHANGE_WINDOW", "title": "生产变更窗口", "category": "release",
        "owner": "change_manager", "blocker": "BLOCKER", "external": True, "status": "OPEN",
        "review": "具名变更单、批准人、窗口、回滚责任人和现场验收记录齐全。",
    },
    {
        "code": "ROLLBACK_DRILL", "title": "生产回滚演练", "category": "resilience",
        "owner": "operations_owner", "blocker": "BLOCKER", "external": False, "status": "OPEN",
        "review": "在 P5 版本完成不删卷、显式确认、配置与数据库可回滚演练。",
    },
    {
        "code": "RISK_ACCEPTANCE", "title": "残余风险接受", "category": "risk",
        "owner": "security_owner", "blocker": "BLOCKER", "external": True, "status": "OPEN",
        "review": "如存在例外，必须有正式批准人、依据、补偿控制、到期日和复核要求。",
    },
    {
        "code": "BUSINESS_APPROVAL", "title": "业务负责人批准", "category": "approval",
        "owner": "business_owner", "blocker": "BLOCKER", "external": True, "status": "OPEN",
        "review": "业务负责人基于唯一 P5 验收包明确签署。",
    },
    {
        "code": "SECURITY_APPROVAL", "title": "安全负责人批准", "category": "approval",
        "owner": "security_owner", "blocker": "BLOCKER", "external": True, "status": "OPEN",
        "review": "安全负责人基于镜像、Secret、越权和残余风险证据明确签署。",
    },
    {
        "code": "OPERATIONS_APPROVAL", "title": "运维负责人批准", "category": "approval",
        "owner": "operations_owner", "blocker": "BLOCKER", "external": True, "status": "OPEN",
        "review": "运维负责人基于容量、监控、备份、变更窗口和回滚证据明确签署。",
    },
)


def install_production_gate_baseline(db: Session) -> None:
    settings = get_settings()
    now = datetime.now(UTC)
    for spec in BASELINE_GATES:
        gate_id = f"GATE-P5-{spec['code']}"
        if db.get(ProductionGate, gate_id) is not None:
            continue
        evidence = list(spec.get("evidence", []))
        evidence_json = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        evidence_hash = hashlib.sha256(evidence_json.encode("utf-8")).hexdigest() if evidence else None
        db.add(ProductionGate(
            gate_id=gate_id,
            gate_code=str(spec["code"]),
            title=str(spec["title"]),
            category=str(spec["category"]),
            tenant_id=settings.platform_tenant_id,
            workspace_id=settings.platform_workspace_id,
            environment="production",
            status=str(spec["status"]),
            owner_role=str(spec["owner"]),
            blocker_level=str(spec["blocker"]),
            external_condition=bool(spec["external"]),
            evidence_json=evidence_json,
            evidence_hash=evidence_hash,
            expires_at=now + timedelta(days=30),
            last_verified_at=now if evidence else None,
            review_requirement=str(spec["review"]),
            version=1,
            created_at=now,
            updated_at=now,
        ))
    db.commit()
