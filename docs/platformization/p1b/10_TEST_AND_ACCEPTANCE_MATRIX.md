# P1B 测试与验收矩阵

更新时间：2026-07-31

## 1. 验收结论

- `P1B_IMPLEMENTATION = PASS`
- `MULTI_SCENARIO = PASS`
- `SQLBOT_SHADOW = RUNTIME_PENDING`
- `SQLBOT_CANARY_ELIGIBLE = false`
- `P0_EXTERNAL_SECURITY = PENDING`
- `P2_ENTRY = NOT_ALLOWED`

P1B 平台代码、第二场景、迁移、模拟数据、指标、Connector、自有 UI 和回退
机制已通过本地实现验收。固定 SQLBot 镜像、真实模型和模拟 datasource 尚未
形成运行证据，因此不把 Mock、离线 Golden 合同或 Adapter 测试冒充真实
NL2SQL 执行准确率，也不允许进入用户可见 SQLBot Canary。

## 2. 强制回归

| 验收项 | 实际执行方式 | 结果 |
|---|---|---|
| 后端全量 | 4 个独立临时 SQLite 数据库分片，覆盖所有测试模块 | 140/140 PASS |
| 导入修复专项 | SQLBot Adapter、Router、Golden Set | 28/28 PASS |
| Deterministic 固定评测 | `run_chatbi_eval.py` | 40/40 PASS |
| charging_ops 指标 | `verify_p0_5_metric_reconciliation.py` | 15/15，`differences={}` |
| sales_ops 指标 | `verify_sales_ops_metric_reconciliation.py` | 12/12，`differences={}` |
| PostgreSQL DQ | 显式调用 `validate_published_batch` | 20/20 PASS |
| PostgreSQL Alembic | 专用 schema：base → 0012 → base → 0012 | PASS，临时 schema 已删除 |
| Docker smoke | Compose 网络内 API smoke | 6/6 PASS |
| PostgreSQL 只读角色 | 临时 schema/role 负向验证 | 12/12 PASS，均已删除 |
| 前端单测 | Vitest | 3/3 PASS |
| 前端生产构建 | TypeScript + Vite | PASS，39 modules |
| Playwright 全量 | 现有受控 Chromium，单 worker | 18/18 PASS |
| npm audit | 锁定依赖 | 0 vulnerabilities |

后端源代码中有 111 个 `test_*` 函数，参数化后实际收集为 140 个 pytest
case。完整串行命令因每用例重建全 Schema 在两小时后只完成约 51%；随后在
不跳过用例、不修改断言的前提下按文件拆为四个隔离分片，实际结果为：

```text
shard-1: 75/75 PASS
shard-2: 33/33 PASS
shard-3: 16/16 PASS
shard-4: 16/16 PASS
total:  140/140 PASS
```

最终导入顺序修复 `fe078ad` 完成后，受影响的 Adapter、Router 和 Golden
测试另行执行 `28/28 PASS`；全新 Python 进程直接导入 SQLBotEngine 并执行
健康检查通过。

## 3. P1B 专项验收

| 专项 | 结果 | 边界 |
|---|---|---|
| SQLBot Adapter | 19 个 pytest case PASS | HTTP Mock，只证明合同 |
| Query Security | 15/15 PASS | 自由 SQL、写入、越权均拒绝 |
| MySQL Connector | 24/24 PASS | 隔离驱动模拟，非真实 MySQL 服务器 |
| EngineRouter | 6/6 PASS | 五模式、无静默 fallback |
| Platform Canary | 9/9 纯合同 + 2/2 ACTIVE 消费者 PASS | SQLBot Runtime 未放行 |
| Shadow 持久化 | PASS | SQLBot 真实双跑仍 PENDING |
| sales_ops | 2/2 单元/集成 + 12/12 指标 PASS | 固定 seed 模拟数据 |
| 双场景 API | PASS | 跨用户、跨场景会话拒绝 |
| 场景禁用 | PASS | sales_ops 禁用后 charging_ops 不受影响 |
| Golden Set | 100/100 离线合同 PASS | 不是 SQLBot 执行准确率 |
| Golden 安全候选 | 10/10 被 Query Guard 拒绝 | 危险/权限攻击成功数 0 |

跨场景、越权和危险 SQL 成功数均为 0。SQLBot 故障在 SHADOW 中不影响
DeterministicEngine 主结果；CANARY/SQLBOT_ENABLED 下故障返回明确错误，
不存在静默 fallback。

## 4. Golden Set 分布与运行指标

`tests/evaluation/nl2sql_dual_engine_v1.json` 共 100 条：

| 类别 | 数量 |
|---|---:|
| 单指标 | 20 |
| 筛选和排序 | 20 |
| 趋势、同比和环比 | 20 |
| 多表和多维度 | 20 |
| 歧义、安全和拒绝 | 20 |

场景分布为 charging_ops 48、sales_ops 52。离线校验覆盖结构、场景指标和
维度引用、拒答标签以及 Query Guard 安全候选。

以下指标必须等待固定 SQLBot Runtime、模型和模拟 datasource 可用后真实
执行，目前全部为 `null`，不得推算：

- SQL 执行成功率；
- Execution Accuracy；
- 指标值、时间范围和维度准确率；
- 权限违规率；
- 幻觉表率和幻觉字段率；
- 拒答准确率；
- P50/P95；
- Token 使用；
- Shadow 一致率。

因此总体 Execution Accuracy ≥ 90%、幻觉率 ≤ 2%、拒答准确率 ≥ 95% 等
SQLBot Canary 阈值尚未评估，`canary_eligible=false`。

## 5. PostgreSQL 与数据不变性

- Alembic：`0012 (head)`；
- 表：56；
- 总行数：653029；
- charging_ops 充电会话：300000；
- sales_ops 订单：50000；
- sales_ops 订单行：82514；
- sales_ops 客户：8000；
- sales_ops 产品：120；
- sales seed：`20260730`；
- sales seed run：`SALES-SIM-v1-20260730`；
- 所有经营数据：模拟数据。

迁移验证只使用专用临时 schema，业务 schema 未升降级；没有删除数据库卷。

## 6. SQLBot 真实健康状态

- 固定引用：`dataease/sqlbot:v1.8.0`；
- 本机镜像：不存在；
- SQLBot 容器：未启动；
- 隔离 Compose：缺少未跟踪的必需秘密时 fail-closed；
- 平台健康：`enabled=false`、`runtime_verified=false`、`status=DISABLED`；
- 上游真实健康：`PENDING`。

这是一项正确的阻断状态，不是健康检查 PASS。Mock Transport 只用于 Adapter
标准化、会话隔离、超时、熔断和安全合同测试。

## 7. 安全与真实性

- 高置信度秘密字面量扫描：0 命中；
- 新增非 example `.env` 文件：0；
- 四份用户源文档：未跟踪、未修改、未提交；
- 外部 datasource：未连接；
- SQLBot/外部 MySQL：未伪造运行结果；
- 所有页面和结果继续标记模拟数据；
- 未宣称生产上线、真实客户或真实经营收益。

## 8. 实际命令摘要

```text
pytest -q <四个互斥文件分片>
pytest -q test_sqlbot_adapter.py test_engine_router.py test_dual_engine_golden.py
python scripts/verify_alembic_schema_cycle.py
validate_published_batch(SessionLocal())
python scripts/verify_p0_5_metric_reconciliation.py
python scripts/verify_sales_ops_metric_reconciliation.py
python scripts/run_chatbi_eval.py
python scripts/run_dual_engine_eval.py
python scripts/docker_smoke.py
python scripts/verify_chatbi_readonly_role.py
npm.cmd test
npm.cmd run build
npm.cmd audit --audit-level=high
npm.cmd run e2e
git diff --check
git fetch origin --prune
```

PowerShell 禁止执行 `npm.ps1` 时使用同一安装中的 `npm.cmd`，没有修改系统
执行策略。Docker smoke 在 Compose 网络中使用受信 Host Header，没有放宽
TrustedHost 配置。
