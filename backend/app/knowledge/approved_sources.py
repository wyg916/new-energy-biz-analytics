"""Explicit P2A knowledge source manifest.

Every entry is a reviewed repository document. Runtime ingestion is fail-closed:
being present on disk is insufficient unless the relative path is listed here.
"""

APPROVED_SOURCE_PATHS = frozenset({
    "docs/00_PROJECT_FACT_BASELINE.md",
    "docs/data_contract_v0.1.md",
    "docs/metric_dictionary_v0.1.md",
    "docs/query_plan_contract_v0.1.md",
    "docs/rbac_and_sql_security_contract_v0.1.md",
    "docs/platformization/p1b/06_SALES_OPS_SCENARIO.md",
    "docs/v2/V2_business_alerts_UI_acceptance.md",
    "docs/adr/ADR-002-SCENARIO-PACKAGE-BOUNDARY.md",
    "docs/adr/ADR-003-DETERMINISTIC-QUERY-ENGINE.md",
    "docs/adr/ADR-005-IDENTITY-AND-PERMISSION-BEFORE-RETRIEVAL.md",
    "docs/platformization/rag41/00_SCOPE_AND_FACT_BOUNDARY.md",
    "docs/platformization/rag41/01_ARCHITECTURE_SECURITY_AND_GOVERNANCE.md",
    "docs/platformization/rag41/02_MIGRATION_COLD_START_AND_ROLLBACK.md",
    "docs/knowledge_baseline/v1/KB01_15项核心指标定义.md",
    "docs/knowledge_baseline/v1/KB02_数据字典.md",
    "docs/knowledge_baseline/v1/KB03_charging_ops业务规则.md",
    "docs/knowledge_baseline/v1/KB04_sales_ops业务规则.md",
    "docs/knowledge_baseline/v1/KB05_收入与成本计算规则.md",
    "docs/knowledge_baseline/v1/KB06_数据接入说明.md",
    "docs/knowledge_baseline/v1/KB07_业务分析方法.md",
    "docs/knowledge_baseline/v1/KB08_SQL安全规则.md",
    "docs/knowledge_baseline/v1/KB09_项目功能使用说明.md",
    "docs/knowledge_baseline/v1/KB00_知识基线说明.md",
})
