# P0 当前事实基线

更新时间：2026-07-30。该文件记录本轮开始时可从代码、数据库和运行命令直接验证的事实；目标设计不得反向改写当前事实。

## 真实性分层

| 层级 | 本轮事实 |
| --- | --- |
| 当前已实现 | 模块化单体；15 项 charging_ops 指标；受控 Query Plan → 确定性参数化 SQL → Query Guard → 只读查询接口 → Answer Guard；数据接入暂存、质量、审批、不可变发布快照；报告草稿；角色与区域过滤 |
| 当前已测试 | 前端 Vitest 3 项与生产构建通过；本轮后端完整、E2E、PostgreSQL 迁移与数据质量结果见 `12_ACCEPTANCE_TEST_MATRIX.md` |
| 历史证据 | 2026-07-29 P0.6 证据曾记录 60 个后端测试、3 个前端测试、13 个 E2E、40 个固定评测、6 个 smoke，以及 507,283 行恢复结果；它不是本轮重跑结论 |
| 模拟数据 | 固定随机种子，时间范围 2025-01-01 至 2026-06-30；不得称为真实企业数据 |
| 未实现 | 通用元数据发现、可复用 Connector SDK、原子 ACTIVE 语义版本、多租户、SSO/OIDC、SQLBot 双引擎、RAG、长期记忆、通知/订阅/工单 |

## 版本与仓库

- 起始分支：`feature/v2-productization`；起始提交：`1a01b9691fa607237e49fb7d89259c827e4a1cd6`。
- 工作分支：`refactor/chatbi-platformization-p0`。
- 远端：`origin=https://github.com/wyg916/new-energy-biz-analytics.git`。
- 起始工作区含四个用户未跟踪文档，本工作包不修改、不暂存、不提交它们。
- 当前 OpenAPI 为 26 条业务路径；Alembic head 为 `0006`。

## 运行与数据

- 本轮开始时 Docker Engine 不可连接，因此容器 PostgreSQL、Redis、Nginx 和浏览器 E2E 不构成当前通过证据。
- 本地 `backend/data/alpha.db` 有 25 张表、Alembic 版本 `0006`，业务表行数为 0；其数据质量检查因空库失败，不能代替历史容器数据。
- 私有部署材料、备份恢复、冷安装和迁移校验脚本已存在；本轮是否可运行以验收矩阵为准。

## 关键事实差距

1. 已发布数据集只形成 `PublishedStationSnapshot`；尚无 ACTIVE 语义指针、原子切换或回滚 API。
2. `DashboardService.station_analysis` 仅在期间、授权场站覆盖和指标集合同时匹配时消费快照，否则消费平台事实表；其他看板、诊断、报告和 ChatBI 主要消费事实表。
3. 因此“发布成功”不等于“所有正式消费者已激活到同一数据版本”。
4. 数据接入支持 CSV/XLSX、PostgreSQL、MySQL 和 allowlist REST GET 的真实解析/试读，但字段标准固定为 charging_ops 场站经营八字段，不是通用企业元数据连接器。
5. 当前身份模型是单客户环境下的三个角色及区域范围，不具备 tenant/org/workspace 隔离语义。
6. Query Guard 是应用层安全边界；当前未证明查询执行使用独立数据库只读角色。
7. Redis 存在于部署编排，但结构化会话工作记忆仍为应用内实现。

## 冲突处理

- `项目当前状态与二次开发接手报告.md` 是用户未跟踪文件，内容停留在较早提交和 `0005`；当前代码和已提交 P0.6 证据优先。
- 历史证据与当前空 SQLite 或不可用 Docker 冲突时，报告“历史通过、当前未验证”，不得静默沿用历史结论。
- 输入蓝图含疑似明文凭据；该内容不进入仓库，必须在仓库外完成撤销与轮换。

