# P0 验收测试矩阵

更新时间：2026-07-30。`本轮` 只记录当前工作分支实际命令；`历史` 不算本轮通过。

| 能力 | 命令/证据 | 期望 | 本轮状态 |
| --- | --- | --- | --- |
| 前端单元 | `npm.cmd test -- --run` | 全部通过 | PASS，3/3 |
| 前端构建 | `npm.cmd run build` | TypeScript 与 Vite 成功 | PASS，39 modules |
| 后端全量 | `.venv\Scripts\python.exe -m pytest backend\tests -q` | 全部通过 | PASS，61/61，1249.8 秒 |
| 发布失败事务 | 指定 `test_failed_publication_rolls_back_workflow_before_failure_audit` + dashboard tests | 审批/数据集不被失败审计误提交 | PASS，4/4 |
| 危险 SQL | `backend/tests/test_query_security.py` | 写操作、多语句、注释逃逸等拒绝 | PASS，包含在后端 61/61 |
| 生产弱配置 | `backend/tests/test_config.py` | 弱密钥/SQLite/HTTP/demo 等拒绝 | PASS，包含在后端 61/61 |
| 无接入 fallback | Playwright 路由 503 | 显示 Blocked，不显示替代业务数据 | PASS，1/1（本地 FastAPI + Vite + 系统 Chrome） |
| 真实性标签 | UI/API 回归 | 模拟数据、时间、来源、run_id/状态 | PASS，API 回归 + 前端构建；新增发布/激活边界断言 |
| 指标回归 | `scripts/verify_p0_5_metric_reconciliation.py` | 15 指标/消费者对账 | Docker 阻塞 |
| Alembic 循环 | `scripts/verify_alembic_schema_cycle.py` | 动态 head→previous→head | Docker 阻塞 |
| DQ | `validate_published_batch` | 固定规则通过 | 本地空 SQLite 按预期失败 DQ-015/016/017/018/020；Docker 完整批次重跑阻塞 |
| RBAC | 后端 auth/security tests | 未授权和跨区域拒绝 | PASS，包含在后端 61/61 |
| E2E 收集 | `playwright test --list` | 规范可解析 | PASS，14 tests/14 files |
| E2E 全量 | `npm.cmd run e2e` | 功能链路通过且无跟踪目录副作用 | Docker/PostgreSQL 阻塞；所有规范已移除跟踪证据目录写入 |
| 固定评测 | `scripts/run_chatbi_eval.py` | Query Plan 金标集通过且默认无工作区写入 | PASS，40/40，前后 `git status` 一致 |
| 依赖审计 | `npm.cmd audit --audit-level=high` | 高危漏洞 0 | PASS，0 vulnerabilities |
| Python 编译 | `python -m compileall` | 后端与修改脚本可编译 | PASS |
| 数据库行数 | SQLite 只读计数 | 如实报告当前库 | 当前本地 25 表/18 行：alembic 1、用户 3、审计 7、数据集 1、数据源 5、场景发布 1；业务事实 0。容器不可用 |
| 凭据安全 | 跟踪文件常见密钥/连接串模式扫描 + 外部轮换证明 | 仓库无秘密，附件凭据已撤销 | 跟踪文件扫描 PASS；外部轮换 BLOCKED |

## 历史参考（不计本轮）

`docs/v2/evidence/p0_6/README.md` 记录 2026-07-29：后端 60、前端 3、E2E 13、固定评测 40、smoke 6，迁移 `0006→0005→0006`，恢复 25 表/507,283 行。若当前环境未重跑，只能表述为“历史证据曾通过”。

## 通过规则

- 任一 P0 安全负向测试失败、SQL Guard 可绕过、数据接入 fallback 恢复、事务回滚失败或凭据未轮换，结论必须是 `P0 NOT PASS`。
- Docker 不可用导致 PostgreSQL/E2E/DQ/迁移未验证时，不得用 SQLite 或历史证据替代。
- 本机 Docker Desktop 已尝试启动，但 WSL 引擎返回 `Wsl/Service/CreateInstance/HCS_E_CONNECTION_TIMEOUT`；随后已恢复到启动前未运行状态。
- 禁止删除、跳过或弱化失败测试。
