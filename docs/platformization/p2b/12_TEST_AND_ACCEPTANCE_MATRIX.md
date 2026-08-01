# P2B 测试与验收矩阵

## 结论

`P2B_IMPLEMENTATION=PASS`，`SQLBOT_QUALITY_PATCH=CONDITIONAL`，
`SQLBOT_CANARY_ELIGIBLE=false`。所有业务数据均为固定种子模拟数据，时间范围为
2025-01-01 至 2026-06-30；确定性引擎继续生成全部用户主答案。

## Memory / Skill 固定评测

| 轨道 | 类别 | 数量 | 结果 |
| --- | --- | ---: | --- |
| Memory | Working 上下文继承 | 10 | 10/10 |
| Memory | Semantic 写入与纠正 | 8 | 8/8 |
| Memory | Episodic 回放与检索 | 8 | 8/8 |
| Memory | 权限与隔离 | 8 | 8/8 |
| Memory | 过期、删除与冲突 | 6 | 6/6 |
| Skill | revenue decline | 10 | 10/10 |
| Skill | order anomaly | 8 | 8/8 |
| Skill | gross profit | 8 | 8/8 |
| Skill | station efficiency | 7 | 7/7 |
| Skill | report generation | 7 | 7/7 |

精确 40+40 行为节点在隔离共享内存 SQLite 中运行，80/80 通过。报告器合同同时验证
分布必须完全匹配、case_id 唯一和安全计数归零。固定测试观察指标为：上下文继承、写入、
作用域、召回、冲突识别、Skill 选择、步骤完成、校验与回放成功率均为 1.0；P50=3ms、
P95=7ms；fixture 存储增长 400 bytes；Token 变化 0。该延迟是隔离测试观察值，不代表
生产负载性能。

安全底线全部通过：跨租户、跨用户私有、跨场景私有、删除后召回、未审核程序激活、
Secret 写入和 Prompt Injection 覆盖系统规则的成功数均为 0。

## 回归矩阵

| 范围 | 命令/证据 | 结果 |
| --- | --- | --- |
| 后端全量 | Docker，只读完整目录挂载，唯一共享内存库 | 295/295 PASS |
| Deterministic | 固定评测 | 40/40 PASS |
| charging_ops 指标 | PostgreSQL 对账 | 15/15 PASS，差异 `{}` |
| sales_ops 指标 | PostgreSQL 对账 | 12/12 PASS，差异 `{}` |
| 数据质量 | 固定检查 | 20/20 PASS |
| Query Security | 安全负向 | 15/15 PASS |
| SQLBot 聚焦 | parser、Guard、LIMIT、binding | 43/43 PASS |
| Docker Smoke | API/DB/Redis/路由 | 6/6 PASS |
| RAG | 固定评测 | 60/60 PASS |
| Response Composer | 固定契约 | 7/7 PASS |
| Vitest | 前端单测 | 3/3 PASS |
| 前端构建 | `npm run build` | PASS，43 modules |
| Playwright | Chromium 位于工作树 `.cache` | 20/20 PASS |
| npm audit | 前端依赖审计 | 0 vulnerabilities |

全量回归以 `/workspace` 原始目录结构挂载 `backend/docs/tests/scripts/deploy/scenarios/samples`，
消除了早期试跑中因缺少 RAG 文档和 CSV 参数样本造成的调用错误。pytest 的只读缓存警告
不影响测试结果。

## SQLBot 限时复评

| 集合 | 计划 | 本轮实际 | 状态 |
| --- | ---: | ---: | --- |
| Smoke | 10 | 0 外部请求 | BLOCKED |
| 代表性 Golden | 30 | 0 外部请求 | BLOCKED |
| Shadow | 20 | 0 外部请求 | BLOCKED |

P2A 容器未导出评测脚本要求的 CredentialReference，脚本在外部请求前明确失败。没有把
离线 100/100 或历史 P2A 结果冒充本轮真实结果。Source Binding v2 和 SQLBot 本地安全
补丁已通过回归，但 SQLBot 状态必须保持 CONDITIONAL/SHADOW，Canary 不可开启。

## 迁移与正式模拟数据

- 隔离数据库完整执行 base→head→base→head；临时数据库随后精确清理，未删除卷。
- 正式迁移前平台元数据备份：
  `.cache/p2b-acceptance/p2b_platform_metadata_0014.dump`，SHA256
  `3ACB5DA18B9C3B46A4ACD331171DC0ABEDDCF738A52FA94469FF3C77FA9B6B1E`。
- Alembic `0014`→`p2b_0001`；public 表 62→70，其中 P2B 新表 8 张；数据库迁移前
  176 MB、迁移后即时 177 MB、最终验收 178 MB。
- 核心模拟数据保持：charging session 300,000；sales order 50,000；sales item 82,514；
  charging 指标 15；sales 指标 12。
- 有效开关：`QUERY_ENGINE_MODE=SHADOW`、`PLATFORM_VERSION_ROUTING_ENABLED=true`、
  `SQLBOT_ENGINE_ENABLED=false`、`SQLBOT_RUNTIME_VERIFIED=false`。

## 主要执行命令

```text
docker compose -p renewable-p2b-memory run --rm ... api pytest -q tests
docker compose -p renewable-p2b-memory run --rm ... api pytest -q <40 Memory + 40 Skill selectors>
docker exec renewable-p2b-memory-api-1 alembic current
docker exec renewable-p2b-memory-db-1 psql ... <read-only acceptance queries>
npm test -- --run
npm run build
npx playwright test
npm audit
```

测试数据库和迁移循环使用隔离数据库/临时目录；正式 PostgreSQL 只执行可回滚迁移、种子
验收和只读核验。没有删除数据库卷、弱化测试或写入真实企业数据。
