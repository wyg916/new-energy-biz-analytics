# P1A 范围与基线

更新时间：2026-07-30

## 状态

- 分支：`feat/p1a-platform-foundation`
- 起点：`04349de1d90838844ca79778e80150803e77908e`
- `P0_IMPLEMENTATION = PASS`
- `P0_ACCEPTANCE = CONDITIONAL`
- `P1A_IMPLEMENTATION = PASS`
- `P1B_ENTRY = NOT_ALLOWED`

P0 仍为 `CONDITIONAL` 的唯一原因是仓库外凭据撤销、轮换及访问日志核查尚未获得管理员确认，状态为 `EXTERNAL_PENDING`。

## 已实现范围

1. 通用 Connector SDK 与 PostgreSQL、CSV、Excel、Mock，MySQL 最小插件；
2. 不可变 DatasetVersion、审批、发布、激活和回滚；
3. 通用版本化语义模型；
4. `charging_ops` 场景包；
5. ACTIVE 版本解析与 DeterministicEngine 适配；
6. React 13 步真实数据治理闭环；
7. PostgreSQL 独立只读执行边界；
8. PostgreSQL 迁移、DQ、指标、smoke、E2E 与安全负向验收。

## 非目标

- 完整 SQLBot、RAG、长期 Agent Memory、多 Agent；
- SSO、Kubernetes、第二个业务场景；
- 真实外部企业数据接入；
- Oracle、SQL Server、Doris、ClickHouse；
- 推翻现有 15 项指标或一次性删除兼容层。

## 默认安全状态

- `PLATFORM_VERSION_ROUTING_ENABLED=false`
- `SQLBOT_ENGINE_ENABLED=false`
- `CHATBI_READONLY_EXECUTION_ENABLED=false`

P1A 平台版本已在模拟数据上验证，但默认不替换稳定查询路径；显式开启版本路由后，ACTIVE 场景、语义或数据集任一缺失都会 fail-closed。

## 真实性边界

全部经营数据为固定随机种子生成的模拟数据，数据期为 2025-01-01 至 2026-06-30。四份用户源文档未修改、未跟踪、未提交。
