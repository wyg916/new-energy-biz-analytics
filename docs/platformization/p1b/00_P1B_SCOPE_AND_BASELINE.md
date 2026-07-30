# P1B 范围与基线

更新时间：2026-07-30

## 状态

- 工作包：`P1B-DUAL-ENGINE-SALES-OPS`
- 分支：`feat/p1b-dual-engine-sales-ops`
- 基线分支：`feat/p1a-platform-foundation`
- 基线提交：`d469888027dd5809cf534bbdf25611f755abe4bb`
- `P0_EXTERNAL_SECURITY = PENDING`
- `P1A_ACCEPTANCE = PASS`
- `P1B_DEVELOPMENT = CONDITIONAL_GO`
- `EXTERNAL_DATASOURCE_MODE = DISABLED`
- `SQLBOT_MODE = SHADOW`
- `REMOTE_RUNTIME_UNVERIFIED`

GitHub 实时 `fetch` 在本轮开始时因连接重置失败。本分支按已核验的本地基线继续开发；缓存远端引用与本地基线一致，但不把缓存引用作为实时远端证据。

## 本轮范围

1. 以固定版本、独立配置和独立容器隔离 SQLBot；
2. 在平台 `QueryEngine` 合同下实现 SQLBot Adapter；
3. 实现 `DETERMINISTIC_ONLY`、`SHADOW`、`CANARY`、`SQLBOT_ENABLED` 和 `DISABLED` 路由；
4. 记录双引擎 Shadow 结果级比较；
5. 新增 `sales_ops` 场景包、固定种子模拟数据和 12 项指标；
6. 补齐 MySQL Connector 的预览、画像、批读和分页；
7. 开发、测试环境启用平台版本路由，生产保持关闭，并支持有界 Canary 和立即回退；
8. 在项目自有 React UI 展示场景、版本、引擎、证据、警告和错误状态；
9. 建立不少于 100 条的双场景 NL2SQL 黄金集及安全负向覆盖。

## 非目标

- 完整 RAG、长期 Agent Memory、多 Agent；
- 第三个场景、Kubernetes、完整 SSO；
- SQLBot 用户页面嵌入；
- 自由 SQL 或绕过 Query Guard 的执行入口；
- 真实企业外部数据或真实外部凭据接入；
- 生产发布。

## 冻结安全边界

- charging_ops 现有 15 项核心指标继续由确定性引擎负责，结果不得变化；
- SQLBot 只通过项目后端 Adapter 调用，浏览器不得访问其内部接口或秘密；
- SQLBot 真实运行不可用时只能标记 `SQLBOT_RUNTIME_PENDING`，Mock 只用于合同测试；
- SQLBot 生成的 SQL 必须先经过平台安全策略和受控只读执行边界；若固定版本不支持生成与执行分离，运行时保持禁用；
- 外部数据源模式保持关闭，只允许仓库模拟数据和隔离测试容器；
- 所有页面、报告与证据继续标明“模拟数据”、时间范围、来源和 `run_id`；
- 四份用户源文档保持未跟踪、未修改、未提交。

## 开发与验收顺序

按“实现 → 相关测试 → 修复 → 验收证据 → 独立提交”执行：

1. SQLBot 固定版本、隔离部署、Adapter 和健康检查；
2. 双引擎路由、ShadowEvaluation 和安全边界；
3. sales_ops 场景、模拟数据和 12 项指标；
4. 100 条黄金集、双场景隔离和安全负向；
5. 自有 UI、Canary、MySQL Connector 与全量回归。

## 回滚

- 默认保持生产 `DETERMINISTIC_ONLY`；
- SQLBot 运行模式可立即切回 `DETERMINISTIC_ONLY`；
- 平台版本路由可关闭并回到 P0/P1A 稳定链路；
- 数据迁移必须支持逐级 downgrade；
- 每个工作包通过独立提交使用 `git revert` 回滚。
