# P1B 实施报告

更新时间：2026-07-31

## 1. 工作包

- 名称：`P1B-DUAL-ENGINE-SALES-OPS`
- 基线分支：`feat/p1a-platform-foundation`
- 基线提交：`d469888027dd5809cf534bbdf25611f755abe4bb`
- 实施分支：`feat/p1b-dual-engine-sales-ops`
- 数据分类：模拟数据

本轮完成双引擎平台合同和 sales_ops 第二业务场景，继续使用项目二自有 React
UI。没有把项目改造成自由 SQL、通用聊天机器人、SQLBot iframe 或多 Agent
自动执行系统。

## 2. 实施结论

| 状态 | 结论 |
|---|---|
| `P1B_IMPLEMENTATION` | PASS |
| `MULTI_SCENARIO` | PASS |
| `SQLBOT_ADAPTER` | PASS |
| `SQLBOT_RUNTIME` | PENDING |
| `SQLBOT_SHADOW` | RUNTIME_PENDING |
| `SQLBOT_CANARY_ELIGIBLE` | false |
| `P0_EXTERNAL_SECURITY` | PENDING |
| `P2_ENTRY` | NOT_ALLOWED |

P1B 实现通过不等于 SQLBot 真实运行通过。DeterministicEngine 继续承担
charging_ops 15 项冻结指标和固定管理查询；SQLBot 默认关闭，生产保持
`DETERMINISTIC_ONLY`。

## 3. 已完成内容

### 3.1 SQLBot 隔离与 Adapter

- 固定 SQLBot `v1.8.0` / `b2de038`，不使用 main/latest；
- 独立 `deploy/sqlbot/`、独立网络、卷和本地管理端口；
- 保留上游许可证、Logo 和版权边界；
- 实现 client、contracts、session、mapper、parser、error、health、flags；
- `QueryRequest + QueryContext → QueryResult` 标准化；
- 八维会话隔离、超时、取消、一次受控重建和熔断；
- 浏览器不接触 SQLBot 秘密或内部 chat_id；
- 修复全新进程直接导入 SQLBotEngine 的循环依赖。

固定镜像仍未拉取，真实 SQLBot 健康和调用保持 PENDING。

### 3.2 数据安全与双引擎

- SQLBot SQL 必须通过单 SELECT、表/字段 allowlist、LIMIT 和危险节点校验；
- 绑定 ACTIVE ScenarioVersion、DatasetVersion、SemanticModelVersion；
- 实现 `DETERMINISTIC_ONLY`、`SHADOW`、`CANARY`、
  `SQLBOT_ENABLED`、`DISABLED`；
- 核心问题固定确定性引擎；
- SHADOW 只返回确定性主结果；
- SQLBot 故障和路由拒绝使用明确错误，不静默 fallback；
- 路由、session 和 Shadow 证据持久化，不保存秘密。

### 3.3 sales_ops 第二场景

- 12 文件标准 Scenario Package；
- 固定 seed `20260730`；
- 50000 模拟销售订单、82514 订单行；
- 8000 客户、120 产品；
- 12 项指标、8 类维度；
- ACTIVE Scenario/Dataset/Semantic 生命周期；
- 独立确定性引擎和项目 Response Composer；
- 场景禁用、跨场景拒绝和 charging_ops 不变性验证。

新增 sales_ops 没有在平台 API 核心加入
`if scenario == "sales_ops"`；场景通过 `ScenarioChatServiceRegistry`
注册。

### 3.4 Connector、Canary 与 UI

- MySQL preview/profile/read_batch/pagination/type normalization；
- 只读事务、MAX_EXECUTION_TIME、错误映射和健康合同；
- 开发/测试平台版本路由默认开启，生产默认关闭；
- tenant/workspace/user/scenario/percentage Canary；
- 自有 UI 展示场景、版本、引擎、模式、来源、模拟数据、耗时、SQL、
  Query Plan、Guards、run/trace 和警告；
- 反馈先校验身份、场景和 run，再写 AuditLog；
- 场景切换竞态防护；
- 无 iframe、无 SQLBot 原始回答、无假按钮。

### 3.5 Golden Set

- 100 条，五类各 20；
- charging_ops 48、sales_ops 52；
- 10 条危险 SQL 候选；
- 离线合同 100/100；
- 危险 SQL、权限攻击和跨场景成功数 0；
- Runtime 指标保持 null，SQLBot Canary 不放行。

## 4. 数据库迁移

| 迁移 | 内容 | 降级 |
|---|---|---|
| `0010` | SQLBot session、ShadowEvaluation、route evidence | downgrade 到 0009 |
| `0011` | sales_ops 模拟维度与事实表 | downgrade 到 0010 |
| `0012` | identity/scenario 会话绑定 | downgrade 到 0011 |

PostgreSQL 专用 schema 完整验证：

```text
base → 0012 → base → 0012 PASS
schema_removed=true
existing_volume_deleted=false
```

当前业务数据库为 `0012 (head)`、56 表、653029 行。

## 5. 指标与数据证据

- charging_ops：15/15，`differences={}`；
- sales_ops：12/12，`differences={}`；
- PostgreSQL DQ：20/20；
- charging_ops 会话：300000，冻结事实未改变；
- sales_ops：50000 订单、82514 订单行；
- 所有数据来源：固定规则和 seed 的模拟数据；
- 未连接真实外部数据库/API。

## 6. 测试结果

完整矩阵见 `10_TEST_AND_ACCEPTANCE_MATRIX.md`。核心结论：

- 后端：140/140 PASS；
- 导入修复专项：28/28 PASS；
- Deterministic：40/40 PASS；
- 双场景 Golden 合同：100/100 PASS；
- Query Security：15/15 PASS；
- MySQL Connector：24/24 PASS；
- Docker smoke：6/6 PASS；
- PostgreSQL 只读角色：12/12 PASS；
- Alembic：完整升降级 PASS；
- 前端 Vitest：3/3 PASS；
- 前端 build：PASS；
- Playwright：18/18 PASS；
- npm audit：0 vulnerabilities；
- 高置信度秘密字面量：0；
- 新增非 example `.env`：0。

## 7. 实际修改范围

相对 P1A 基线共修改或新增 95 个文件，7893 行新增、118 行删除，分组为：

- 迁移：`backend/alembic/versions/0010`、`0011`、`0012`；
- API/服务：ChatBI API、service、guard、scenario registry；
- 平台：config、QueryEngine、EngineRouter、Shadow、Context；
- SQLBot Adapter：`backend/app/query_engines/sqlbot/`；
- 数据模型：query routing、sales；
- 场景实现：`backend/app/scenarios/sales_ops/`；
- 场景合同：`scenarios/sales_ops/` 12 文件；
- Connector：MySQL；
- 前端：`overview.tsx/css`、双场景 Playwright；
- 部署：主 Compose、私有部署、`deploy/sqlbot/`；
- 评测：100 条 Golden Set、sales 指标基线和执行脚本；
- 测试：Adapter、Router、Shadow、Sales、MySQL、Canary、双场景、安全；
- 文档：`docs/platformization/p1b/00` 至 `12`。

四份用户源文档保持未跟踪、未修改、未提交。

## 8. 独立提交

```text
8056e40 docs: freeze p1b scope and baseline
c5fd4ff build: add pinned sqlbot isolated deployment
1df86d4 feat: implement sqlbot query engine adapter
e0e84cf feat: add dual engine shadow evaluation
3523714 feat: add sales ops scenario package
89e2ef2 feat: complete mysql preview and batch access
7e0790d feat: add platform canary routing
bb9abbf feat: expose scenario and engine evidence in own ui
d46d2ee test: add multi-scenario nl2sql and security coverage
fe078ad fix: make sqlbot health import order safe
```

最终验收文档提交以本文件提交后的 `git log` 为准。

## 9. 安全与真实性

- SQLBot、MySQL 和外部系统实际不可用时均明确 PENDING；
- 不开放自由 SQL；
- LLM 不直接执行核心 SQL；
- 不允许 Query Guard 绕过；
- 不把模拟数据称为真实企业数据；
- 不宣称生产上线、真实客户或真实经营收益；
- P0 外部凭据轮换确认仍为仓库外 PENDING。

## 10. 回滚

即时逻辑回退：

```text
PLATFORM_VERSION_ROUTING_ENABLED=false
QUERY_ENGINE_MODE=DETERMINISTIC_ONLY
SQLBOT_ENGINE_ENABLED=false
```

代码按独立提交逆序 `git revert`。Schema 可逐级 downgrade，但 `0011 → 0010`
会删除 sales_ops 模拟数据，`0010 → 0009` 会删除 P1B 路由/Shadow 证据，
执行前应导出所需审计记录。无需且不得删除数据库卷。

## 11. 下一阶段

当前不允许进入 P2。先完成：

1. 外部管理员的凭据撤销、轮换和日志核查确认；
2. 固定 SQLBot 镜像与模拟 datasource 真实运行；
3. SQLBot 专用只读角色和 semantic view 负向验收；
4. 100 条真实执行评测达到 Canary 阈值；
5. 危险 SQL、越权和跨场景成功数继续保持 0。
