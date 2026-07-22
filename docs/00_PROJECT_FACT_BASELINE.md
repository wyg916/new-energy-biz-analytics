# 项目事实基线

> 事实日期：2026-07-22
>
> 当前阶段：Phase 1—8 已完成，产品级 Alpha 已通过本地验收
>
> 数据标签：固定种子模拟数据

## 已实现并验证

- FastAPI + React 模块化单体及 PostgreSQL、Redis、Nginx Compose 编排；
- 认证、三类角色、区域数据范围、401/403、审计与生产 fail-closed；
- 可回滚 Alembic 迁移、固定 seed 生成器、30 万会话批次和 20 项数据质量规则；
- 15 项已批准指标语义层、数据库计算和对账；
- 经营驾驶舱、趋势与场站专题，所有数字来自后端数据库；
- 版本化 Query Plan、确定性参数化 SQL Compiler、Query Guard 和只读执行；
- ChatBI 澄清、图表结果、Answer Guard、证据面板和 40 题固定评测；
- 结构化短期会话状态、显式覆盖、用户/会话隔离、TTL 与 analysis_run；
- 环比/同比、同群比较、异常规则、收入/毛利拆解、贡献与关联因素边界；
- 周报/月报草稿、Markdown/CSV 导出、来源/批次/指标版本/run_id 回溯；
- 后端、前端、E2E、安全、数据质量、固定评测和冷环境 Compose 验收。

## 未实现或不在范围

- 企业真实数据、生产部署、真实客户使用与真实经营收益；
- 开放域 LLM、自由生成任意 SQL、长期个人记忆或 RAG；
- DOCX 原生排版和服务端 PDF 生成（当前导出为 Markdown/CSV）；
- 多 Agent、自动交易、自动邮件/企微、工单闭环；
- SSO、生产级多租户、Kubernetes、Kafka、微服务和高可用集群。

## 已执行的验收事实

- 后端 pytest：33/33，通过率 100%，语句覆盖率 89%；
- 前端 Vitest：3/3；生产构建成功；npm audit 已知漏洞 0；
- ChatBI 固定评测：40/40；无硬编码答案；
- 危险 SQL 语料：12/12 拒绝；
- 完整模拟数据：3 区域、6 城市、30 场站、120 设备、10,000 用户、300,000 会话；
- 数据质量：DQ-001—DQ-020 全部通过；
- Docker 烟测：6/6；Playwright 核心旅程：1/1；
- Alembic：空库 upgrade、downgrade、re-upgrade 已验证。

## Git 与真实性边界

开发分支为 `develop/alpha-fast-track`，Phase 1—8 各有独立提交。允许使用“已设计、已批准、已实现、已测试、已验证、模拟数据、规划中”等精确状态标签；不得把 Alpha 验收升级表述为生产验证。
