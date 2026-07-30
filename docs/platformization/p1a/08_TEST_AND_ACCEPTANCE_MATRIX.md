# P1A 测试与验收矩阵

更新时间：2026-07-30

## 运行级门禁

| 门禁 | 命令摘要 | 结果 |
| --- | --- | --- |
| Docker 健康 | `docker compose up -d --build api web` / `docker compose ps` | api/db/redis healthy，web running |
| Alembic 全循环 | `python scripts/verify_alembic_schema_cycle.py` | base→0009→base→0009 PASS；Schema 删除 |
| PostgreSQL DQ | `validate_published_batch`（容器 PostgreSQL） | 20/20 PASS |
| 15 指标 | `verify_p0_5_metric_reconciliation.py` | 15/15，differences `{}` |
| ChatBI 固定评测 | `run_chatbi_eval.py` | 40/40 PASS |
| Docker smoke | `docker_smoke.py` | 6/6 PASS |
| 只读角色 | `verify_chatbi_readonly_role.py` | 12 项 PASS；角色/Schema 删除 |
| PostgreSQL Connector | 临时只读角色运行脚本 | 连接、发现、关系、预览、画像、批读、增量、健康全部 PASS |
| 前端单测 | `npm.cmd test` | 3/3 PASS |
| 前端构建 | `npm.cmd run build` | PASS |
| Playwright E2E | `PLAYWRIGHT_EXECUTABLE_PATH=... npx.cmd playwright test` | 17/17 PASS |

## 代码级测试

| 范围 | 结果 |
| --- | --- |
| Connector SDK | 本轮先前 18/18 PASS；关系发现修改用例 1/1 PASS；PostgreSQL live PASS |
| Dataset Release | 6/6 PASS；PostgreSQL v1/v2 激活回滚 PASS |
| Semantic Registry | 4/4 PASS |
| Scenario Package | 5/5 PASS |
| ACTIVE Query routing | 2/2 PASS |
| Platform Foundation API | 2/2 PASS |
| Readonly Executor | 2/2 PASS |
| Data Integration 关键路径 | 4/4 PASS |
| ChatBI 回归 | 2/2 PASS |
| Query Security | 15/15 PASS |

Connector 与 Query Security 全文件在仓库大 SQLite 文件上曾因每用例 `drop_all/create_all` 超时；停止遗留 one-off 容器后，使用隔离匿名数据卷完成 Query Security 15/15。Connector 修改前全文件 18/18 已通过，修改后单用例与 PostgreSQL live 均通过。超时记录不是断言失败。

## 数据量

- 迁移前：25 表，510639 行，Alembic 0006；
- 迁移后并完成 P1A 运行验证：43 表，510752 行，Alembic 0009；
- 增量 113 行为平台版本、语义、发布、激活、回滚和验收审计；
- 核心事实计数未改变，充电会话仍为 300000。

## 验收结论

- PostgreSQL、版本事务、语义、场景、查询、前端与只读边界：PASS；
- 外部凭据轮换：`EXTERNAL_PENDING`；
- `P1A_IMPLEMENTATION = PASS`；
- `P1B_ENTRY = NOT_ALLOWED`。
