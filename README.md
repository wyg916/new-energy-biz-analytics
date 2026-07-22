# 新能源企业经营分析智能平台（AI 增强 BI）

> **当前状态：快速落地开发，Phase 1—8 已获连续执行授权。**
> **数据状态：Alpha 仅使用规则驱动的模拟数据。**

## 项目定位

本项目面向新能源充电运营经营分析，以统一指标语义层为基础，规划经营驾驶舱、受控智能问数、异常诊断、贡献归因和可审核报告草稿能力。

核心可信链路已经冻结为：

```text
自然语言问题
→ Query Plan
→ 确定性参数化 SQL 编译
→ Query Guard
→ 只读执行
→ 结构化结果
→ Answer Guard
```

本项目不是通用聊天机器人，不开放自由 SQL，不实现自动邮件、工单、跨系统执行或多 Agent 自治。

## 当前已完成

- v1.1 立项设计文档；
- Phase 0 开发准备度评审；
- DEC-01—DEC-10 项目负责人决策冻结；
- Phase 0.1 开发前合同、固定评测集和低保真原型；
- DoR 复审和独立 Git 基线。

“已完成”仅指上述文档和评审产物，不表示产品功能已经实现、测试或部署。

## 当前未完成

- FastAPI 后端；
- React 前端；
- PostgreSQL Schema 和 Alembic 迁移；
- 模拟数据生成器及实际数据；
- 指标服务、驾驶舱、ChatBI、记忆、异常归因和报告功能；
- Docker Compose 运行环境；
- 自动化测试和评测执行结果；
- Alpha 部署和验收。

## 模拟数据边界

Alpha 数据计划覆盖 2025-01-01 至 2026-06-30，包含 3 个区域、6 个城市、30 个场站、约 120 台设备、约 10,000 名模拟用户和约 300,000 次充电会话。数据生成必须使用固定随机种子，覆盖季节性、节假日、设备故障、成本变化、经营异常和数据质量异常。

所有未来页面、报告和导出必须显示：

- `模拟数据`；
- 数据时间；
- 数据来源；
- `run_id`。

## 文档入口

- [开发准备度与 DoR 评审](docs/implementation_readiness_report.md)
- [产品范围基线](docs/project_scope_baseline.md)
- [技术架构基线](docs/architecture_baseline.md)
- [已批准决策](docs/decision_log.md)
- [阶段计划](docs/phase_plan.md)
- [缺失输入](docs/missing_inputs.md)
- [数据合同 v0.1](docs/data_contract_v0.1.md)
- [指标字典 v0.1](docs/metric_dictionary_v0.1.md)
- [Query Plan 合同 v0.1](docs/query_plan_contract_v0.1.md)
- [RBAC 与 SQL 安全合同 v0.1](docs/rbac_and_sql_security_contract_v0.1.md)
- [记忆合同 v0.1](docs/memory_contract_v0.1.md)
- [固定评测集](tests/evaluation/chatbi_evaluation_set_v0.1.json)
- [低保真原型](docs/prototypes/index.html)

## 阶段门

Phase 1 不会由本仓库状态自动启动。只有 DoR 阻断项为 0、所有有条件通过项都有负责人和截止时间，并且项目负责人单独批准 Phase 1 实施卡后，才允许创建工程骨架。

## 真实性声明

本项目目前没有企业生产数据、生产部署、真实客户使用或可归因的经营收益。任何外部介绍都必须区分“已设计、已实现、已测试、已验证、模拟数据、规划中”。
