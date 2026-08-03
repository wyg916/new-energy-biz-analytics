# P5A 当前轮回归收口

## 结论

截至 2026-08-03，本轮在恢复后的 Docker Desktop / WSL2、PostgreSQL 16.14、真实 P5A Keycloak 与固定种子模拟数据上完成当前回归。后端有效结果为 359/359，Docker Smoke 为 6/6，Playwright 为 27/27，Vitest 为 3/3，TypeScript、Vite build 与 npm audit 均通过。该结论只适用于本地预生产候选，不代表正式生产验收通过。

数据范围固定为 2025-01-01 至 2026-06-30；充电会话 300000、销售订单 50000、销售订单明细 82514。前端没有读取 fixture 或静默使用虚构数据兜底。

## 后端当前全量

- 首次使用持久化临时库的全量尝试因 Docker Desktop 的 `DataFileImmediateSync` 创建索引过慢而主动停止；测试数为 0，临时库和测试容器均已移除，证据为 `evidence/p5a-postgres-final-full.json`。
- 第一次四路 tmpfs PostgreSQL 全量收集 359 项，10 项失败；原因仅为测试容器未复制 `deploy`、`scripts`、`samples` 等测试资产，证据为 `evidence/p5a-postgres-final-tmpfs.json`。
- 修正资产复制后四路全量为 356 通过、3 失败；这 3 项均来自 `test_knowledge_lifecycle.py` 的容器内 `docs` 目录嵌套错误，证据为 `evidence/p5a-postgres-final-rerun.json`。
- 第一次知识文件修正复验因 `docs/docs` 嵌套仍有 3 项失败，已保留 `evidence/p5a-postgres-knowledge-rerun.json`；修正复制语法后同文件 4/4 通过，覆盖原 3 个失败节点，证据为 `evidence/p5a-postgres-knowledge-rerun2.json`。
- 门禁合同收紧为精确 28 项后，`test_p5_production_gate_registry.py` 当前复验 5/5 通过，证据为 `evidence/p5a-postgres-gate-rerun.json`。
- 因此有效结果为 359/359、0 failed、0 skipped；不宣称存在一次单轮 359/359 全绿运行。汇总证据为 `evidence/p5a-final-regression-summary.json`。

## 固定评测与数据核对

| 范围 | 当前结果 |
|---|---:|
| Deterministic ChatBI | 40/40 |
| charging_ops 指标对账 | 15/15，差异 0 |
| sales_ops 指标对账 | 12/12，差异 0 |
| Data Quality | 20/20 |
| Memory | 40/40 |
| Skill | 40/40 |
| RAG keyword-only | 60/60 |
| Response Composer | 7/7 |
| Query Security | 15/15 |
| SQLBot 离线聚焦 | 46/46；未执行、未声称外部运行时 |

RAG 保持 `KEYWORD_ONLY`，Vector 未发布。SQLBot 保持 runtime disabled、canary false，主链仍为确定性 Query Plan、参数化 SQL 编译、Query Guard、只读执行和 Answer Guard。

## 前端与浏览器

- Docker Smoke：6/6，使用正式 API、OIDC 会话、PostgreSQL 数据与权限拒绝，证据为 `evidence/docker-smoke-p5a-final.json`。
- Playwright：原业务回归 23/23；真实 Keycloak Authorization Code + PKCE 3/3；精确 28 门禁 No-Go UI 1/1，合计 27/27。
- Vitest：首次与后端四路全量并发时，3 项中 1 项超时；未修改断言，资源竞争结束后重跑 3/3。两份 JUnit 均保留。
- TypeScript、Vite production build：PASS；npm audit：0 vulnerabilities，证据为 `evidence/frontend-static-p5a-final.json` 与 `evidence/npm-audit-p5a-final.json`。
- 原 23 项使用从本轮备份恢复的隔离 tmpfs E2E 数据库，源 P5A 数据库未修改；E2E 服务已停止，未删除任何 P5A 卷。

## 数据库与回滚

当前 `alembic current` 与 `alembic heads` 均为 `p5_0001 (head)`。已有独立数据库迁移合同为 `base -> p5_0001 -> p4_0001 -> p5_0001`，临时数据库已移除；P5A 没有新增模型变更，因此没有创建无意义迁移。

本工作包不修改正式数据、不启用 SQLBot、不进入 P6、不授权生产发布。回滚仅需反向提交本工作包的回归脚本、测试合同和证据文件；数据库无新增迁移需要回滚。
